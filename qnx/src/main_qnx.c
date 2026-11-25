/*
 * main_qnx.c - on-target entry point for the QNX 8.0 build.
 *
 * !!! NOT COMPILED OR RUN YET !!! (No QNX SDP on the dev machine; see
 * platform_qnx.c.) Written against the documented QNX 8.0 / POSIX API
 * for the Phase 5 target build; guarded by __QNXNTO__.
 *
 * Shape of the target program (plan Phase 5, tests T5.1/T5.2):
 *   - A control thread at real-time priority (SCHED_FIFO) owns the
 *     timing controller: it kicks the watchdog, polls supervision
 *     (stop input + watchdogs) and feeds sensor edges.
 *   - The sensor is an optical gate. On real hardware its level comes
 *     from the board input (TODO marker below). Under QEMU there is no
 *     gate, so a simulation thread toggles the level at a configured
 *     period - this is the "simulated optical-gate input" of test
 *     T5.2, used to measure the controller's timing behaviour and
 *     jitter on target.
 *   - The run ends COMPLETE, FAULT or ESTOP and prints a result
 *     summary (cycles, elapsed, mean period, jitter) to the console,
 *     which the host app captures as the target's timing log.
 *
 * Usage on target:  mimforge_controller_qnx <period_seconds>
 * e.g.              mimforge_controller_qnx 1.905   (20 cycles timed)
 */
#ifdef __QNXNTO__

#include <pthread.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "platform.h"
#include "timing_controller.h"

static tc_t g_tc;
static volatile int g_gate_level = 0;
static double g_sim_half_period_s = 0.9525; /* T/2 for the T5.2 demo run */

/* --- simulated optical gate (QEMU test T5.2) -------------------------
 * On real hardware, replace gate_level() with the board input read and
 * delete this thread. */
static void *gate_sim_thread(void *unused) {
    (void)unused;
    struct timespec ts;
    ts.tv_sec = (time_t)g_sim_half_period_s;
    ts.tv_nsec = (long)((g_sim_half_period_s - (double)ts.tv_sec) * 1e9);
    for (;;) {
        nanosleep(&ts, NULL);
        g_gate_level = !g_gate_level;
    }
    return NULL;
}

static int gate_level(void) { return g_gate_level; }

/* --- control thread -------------------------------------------------- */
static void *control_thread(void *unused) {
    (void)unused;
    int last_level = gate_level();
    const struct timespec step = {0, 1000000L}; /* 1 ms poll cadence */

    while (tc_state(&g_tc) != TC_STATE_COMPLETE &&
           tc_state(&g_tc) != TC_STATE_FAULT &&
           tc_state(&g_tc) != TC_STATE_ESTOP) {
        tc_kick(&g_tc);
        tc_poll(&g_tc);

        int level = gate_level();
        if (level != last_level) {
            if (level == 1) tc_on_sensor_edge(&g_tc); /* rising edge */
            last_level = level;
        }
        nanosleep(&step, NULL);
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc > 1) g_sim_half_period_s = atof(argv[1]) / 2.0;

    tc_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.target_cycles = 20;
    cfg.edges_per_cycle = 2; /* gate at the symmetry point */
    cfg.min_edge_interval_ns = 100000000ULL;  /* 100 ms glitch reject */
    cfg.watchdog_timeout_ns = 5000000000ULL;  /* 5 s edge-gap watchdog */
    cfg.kick_deadline_ns = 500000000ULL;      /* 500 ms kick deadline  */

    if (tc_init(&g_tc, &cfg) != TC_OK) {
        fprintf(stderr, "controller init failed\n");
        return 1;
    }
    tc_arm(&g_tc);

    pthread_t gate_thr, ctl_thr;
    pthread_create(&gate_thr, NULL, gate_sim_thread, NULL);

    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
    struct sched_param sp;
    sp.sched_priority = 50; /* real-time priority for the timing loop */
    pthread_attr_setschedparam(&attr, &sp);
    pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
    pthread_create(&ctl_thr, NULL, control_thread, NULL);
    pthread_attr_destroy(&attr);

    tc_release(&g_tc);
    pthread_join(ctl_thr, NULL);

    tc_result_t r;
    tc_get_result(&g_tc, &r);
    printf("state=%s fault=%s cycles=%u edges=%u rejected=%u\n",
           tc_state_name(tc_state(&g_tc)), tc_fault_name(tc_fault(&g_tc)),
           (unsigned)r.cycles_completed, (unsigned)r.edges_accepted,
           (unsigned)r.edges_rejected);
    printf("elapsed=%.4f s  mean period=%.6f s  min=%.6f  max=%.6f  "
           "jitter=%.6f s\n",
           (double)r.elapsed_ns / 1e9, r.mean_period_s, r.min_period_s,
           r.max_period_s, r.jitter_s);
    return (tc_state(&g_tc) == TC_STATE_COMPLETE) ? 0 : 2;
}

#endif /* __QNXNTO__ */
