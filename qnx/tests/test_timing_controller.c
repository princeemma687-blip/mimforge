/*
 * test_timing_controller.c - host test harness for the generic timing
 * controller.
 *
 * Drives the controller through the host platform's virtual clock, so
 * every measurement is deterministic and can be checked against
 * expected values exactly.
 *
 * The worked-example test feeds synthetic optical-gate edges derived
 * from the demo template's readings table (test DATA: lengths
 * 0.50-0.90 m, mean time for 20 cycles 28.4-38.1 s, expected slope
 * 4.03 s^2/m, expected derived constant 9.8, tolerance band +/-5%
 * around 9.81 with a +/-3% target). The gate sits at the symmetry
 * point, so it produces 2 edges per cycle - hence edges_per_cycle = 2
 * and 41 edges time exactly 20 cycles. The controller core itself
 * contains none of these specifics; they live only in this harness
 * and in the template data file.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "platform.h"
#include "platform_host.h"
#include "timing_controller.h"

static int g_checks = 0;
static int g_failures = 0;

#define CHECK(cond, ...)                       \
    do {                                       \
        g_checks++;                            \
        if (!(cond)) {                         \
            g_failures++;                      \
            printf("  FAIL: ");                \
            printf(__VA_ARGS__);               \
            printf("\n");                      \
        }                                      \
    } while (0)

static tc_config_t base_cfg(void) {
    tc_config_t c;
    memset(&c, 0, sizeof(c));
    c.target_cycles = 20;
    c.edges_per_cycle = 2;                    /* gate at symmetry point */
    c.min_edge_interval_ns = 100000000ULL;    /* 100 ms glitch reject   */
    c.watchdog_timeout_ns = 5000000000ULL;    /* 5 s edge-gap watchdog  */
    c.kick_deadline_ns = 0;                   /* enabled per-test       */
    return c;
}

/* Deterministic pseudo-random source for edge jitter (LCG). */
static uint64_t g_lcg = 0;
static double lcg_uniform(void) {
    g_lcg = g_lcg * 6364136223846793005ULL + 1442695040888963407ULL;
    return (double)(g_lcg >> 11) / (double)(1ULL << 53);
}

/* Feed `total_edges` edges spaced period_s/2 apart, the first at
 * first_edge_s (absolute, seconds on the virtual clock). Optional
 * per-edge jitter of +/- jitter_ns and optional glitch injection: a
 * spurious edge glitch_offset_ns after each of the first
 * glitch_first_n real edges. */
static void feed_edges(tc_t *tc, double period_s, int total_edges,
                       double first_edge_s, int64_t jitter_ns,
                       int glitch_first_n, uint64_t glitch_offset_ns) {
    double half = period_s / 2.0;
    for (int k = 0; k < total_edges; k++) {
        double t = first_edge_s + (double)k * half;
        int64_t j = 0;
        if (jitter_ns > 0)
            j = (int64_t)((lcg_uniform() * 2.0 - 1.0) * (double)jitter_ns);
        plat_host_set_time_ns((uint64_t)(t * 1e9) + (uint64_t)j);
        tc_on_sensor_edge(tc);
        if (glitch_first_n > 0 && k < glitch_first_n) {
            plat_host_advance_ns(glitch_offset_ns);
            tc_on_sensor_edge(tc); /* spurious bounce edge */
        }
    }
}

/* ------------------------------------------------------------------ */
/* 1. Worked example: reproduce the readings table, slope, constant.  */
/* ------------------------------------------------------------------ */
static void test_worked_example(void) {
    printf("[1] Worked example: 20 cycles at 5 lengths (clean edges)\n");
    static const double L_m[5] = {0.90, 0.80, 0.70, 0.60, 0.50};
    static const double mean_t_exp[5] = {38.1, 35.9, 33.6, 31.1, 28.4};
    static const double T_exp[5] = {1.91, 1.80, 1.68, 1.56, 1.42};
    double T2_meas[5];
    double worst_dt = 0.0;

    printf("    L (m) | mean t meas | mean t exp | T meas | T exp | T^2 meas\n");
    for (int i = 0; i < 5; i++) {
        tc_t tc;
        tc_config_t cfg = base_cfg();
        CHECK(tc_init(&tc, &cfg) == TC_OK, "init row %d", i);
        plat_host_set_estop(false);
        plat_host_set_time_ns(1000000000ULL); /* release at t = 1.000 s */
        CHECK(tc_arm(&tc) == TC_OK, "arm row %d", i);
        CHECK(tc_release(&tc) == TC_OK, "release row %d", i);
        CHECK(plat_release_get() == true, "output on after release");

        double period = mean_t_exp[i] / 20.0;
        feed_edges(&tc, period, 41, 1.25, 0, 0, 0);

        tc_result_t r;
        tc_get_result(&tc, &r);
        CHECK(tc_state(&tc) == TC_STATE_COMPLETE, "row %d completes", i);
        CHECK(r.cycles_completed == 20, "row %d cycles = %u", i,
              (unsigned)r.cycles_completed);
        CHECK(r.edges_accepted == 41, "row %d edges = %u", i,
              (unsigned)r.edges_accepted);
        CHECK(r.edges_rejected == 0, "row %d rejected = %u", i,
              (unsigned)r.edges_rejected);
        CHECK(plat_release_get() == false, "output safe after complete");
        CHECK(r.release_to_first_edge_ns == 250000000ULL,
              "row %d release->first edge = %llu ns", i,
              (unsigned long long)r.release_to_first_edge_ns);

        double mean_t = (double)r.elapsed_ns / 1e9;
        double dt = fabs(mean_t - mean_t_exp[i]);
        if (dt > worst_dt) worst_dt = dt;
        CHECK(dt < 0.001, "row %d mean t %.4f vs expected %.1f", i,
              mean_t, mean_t_exp[i]);
        double T = mean_t / 20.0;
        CHECK(fabs(T - T_exp[i]) < 0.01, "row %d T %.4f vs %.2f", i, T,
              T_exp[i]);
        T2_meas[i] = T * T;
        printf("    %.2f  |   %8.4f    |   %5.1f     | %.4f | %.2f  | %.4f\n",
               L_m[i], mean_t, mean_t_exp[i], T, T_exp[i], T2_meas[i]);
    }
    printf("    worst mean-t deviation: %.6f s\n", worst_dt);

    /* Least-squares slope of T^2 vs L, then the derived constant. */
    double xm = 0.0, ym = 0.0;
    for (int i = 0; i < 5; i++) { xm += L_m[i]; ym += T2_meas[i]; }
    xm /= 5.0; ym /= 5.0;
    double num = 0.0, den = 0.0;
    for (int i = 0; i < 5; i++) {
        num += (L_m[i] - xm) * (T2_meas[i] - ym);
        den += (L_m[i] - xm) * (L_m[i] - xm);
    }
    double slope = num / den;
    double pi = acos(-1.0);
    double g = 4.0 * pi * pi / slope;
    double g_err_pct = (g - 9.81) / 9.81 * 100.0;
    printf("    slope = %.4f s^2/m (template: 4.03), derived constant = "
           "%.4f (expected 9.81, error %+.2f%%)\n",
           slope, g, g_err_pct);
    CHECK(fabs(slope - 4.03) / 4.03 < 0.01, "slope within 1%% of 4.03");
    CHECK(fabs(g_err_pct) < 5.0, "constant inside the +/-5%% band");
    CHECK(fabs(g_err_pct) < 3.0, "constant inside the +/-3%% target band");
}

/* ------------------------------------------------------------------ */
/* 2. Jittered edges: mean period stays accurate, jitter reported.    */
/* ------------------------------------------------------------------ */
static void test_jitter(void) {
    printf("[2] Jittered edges (+/-2 ms) at L = 0.90 m\n");
    tc_t tc;
    tc_config_t cfg = base_cfg();
    tc_init(&tc, &cfg);
    plat_host_set_estop(false);
    plat_host_set_time_ns(1000000000ULL);
    tc_arm(&tc);
    tc_release(&tc);
    g_lcg = 12345;
    feed_edges(&tc, 38.1 / 20.0, 41, 1.25, 2000000, 0, 0);

    tc_result_t r;
    tc_get_result(&tc, &r);
    printf("    mean period %.6f s (true 1.905000), jitter %.6f s, "
           "rejected %u\n",
           r.mean_period_s, r.jitter_s, (unsigned)r.edges_rejected);
    CHECK(tc_state(&tc) == TC_STATE_COMPLETE, "jittered run completes");
    CHECK(r.edges_rejected == 0, "no false glitch rejections");
    CHECK(fabs(r.mean_period_s - 1.905) / 1.905 < 0.005,
          "mean period within 0.5%% under jitter");
    CHECK(r.jitter_s > 0.0 && r.jitter_s < 0.01,
          "jitter reported and bounded: %.6f", r.jitter_s);
}

/* ------------------------------------------------------------------ */
/* 3. Glitch rejection: bounce edges do not disturb the timing.       */
/* ------------------------------------------------------------------ */
static void test_glitch_rejection(void) {
    printf("[3] Glitch rejection: bounce edge 5 ms after real edges\n");
    tc_t tc;
    tc_config_t cfg = base_cfg();
    tc_init(&tc, &cfg);
    plat_host_set_estop(false);
    plat_host_set_time_ns(1000000000ULL);
    tc_arm(&tc);
    tc_release(&tc);
    feed_edges(&tc, 28.4 / 20.0, 41, 1.25, 0, 10, 5000000ULL);

    tc_result_t r;
    tc_get_result(&tc, &r);
    double mean_t = (double)r.elapsed_ns / 1e9;
    printf("    accepted %u, rejected %u, mean t %.4f s (expected 28.4)\n",
           (unsigned)r.edges_accepted, (unsigned)r.edges_rejected, mean_t);
    CHECK(tc_state(&tc) == TC_STATE_COMPLETE, "run completes");
    CHECK(r.edges_accepted == 41, "accepted = %u", (unsigned)r.edges_accepted);
    CHECK(r.edges_rejected == 10, "rejected = %u", (unsigned)r.edges_rejected);
    CHECK(fabs(mean_t - 28.4) < 0.001, "timing undisturbed by glitches");
}

/* ------------------------------------------------------------------ */
/* 4. Watchdog: edges stop arriving mid-run -> fault, output safe.    */
/* ------------------------------------------------------------------ */
static void test_watchdog_edge_gap(void) {
    printf("[4] Watchdog: edge gap mid-run\n");
    tc_t tc;
    tc_config_t cfg = base_cfg();
    tc_init(&tc, &cfg);
    plat_host_set_estop(false);
    plat_host_set_time_ns(0);
    tc_arm(&tc);
    tc_release(&tc);
    feed_edges(&tc, 38.1 / 20.0, 11, 0.25, 0, 0, 0); /* then silence */

    plat_host_advance_ns(6000000000ULL); /* 6 s > 5 s watchdog */
    tc_poll(&tc);
    printf("    state %s, fault %s, output %s\n", tc_state_name(tc_state(&tc)),
           tc_fault_name(tc_fault(&tc)), plat_release_get() ? "ON" : "OFF");
    CHECK(tc_state(&tc) == TC_STATE_FAULT, "watchdog faults the run");
    CHECK(tc_fault(&tc) == TC_FAULT_WATCHDOG_EDGE_GAP, "fault code");
    CHECK(plat_release_get() == false, "output driven safe");
    CHECK(tc_reset(&tc) == TC_OK && tc_state(&tc) == TC_STATE_IDLE,
          "deliberate reset recovers to idle");
}

/* ------------------------------------------------------------------ */
/* 5. Watchdog: supervising loop stops kicking -> fault.              */
/* ------------------------------------------------------------------ */
static void test_watchdog_kick(void) {
    printf("[5] Watchdog: kick deadline\n");
    tc_t tc;
    tc_config_t cfg = base_cfg();
    cfg.kick_deadline_ns = 2000000000ULL;   /* 2 s */
    cfg.watchdog_timeout_ns = 30000000000ULL; /* keep edge-gap out of the way */
    tc_init(&tc, &cfg);
    plat_host_set_estop(false);
    plat_host_set_time_ns(0);
    tc_arm(&tc);
    tc_release(&tc);

    /* Healthy loop: kick + poll every 0.5 s for 3 s -> no fault. */
    for (int i = 0; i < 6; i++) {
        plat_host_advance_ns(500000000ULL);
        tc_kick(&tc);
        tc_poll(&tc);
    }
    CHECK(tc_state(&tc) == TC_STATE_RELEASED, "kicked loop stays healthy");

    /* Loop hangs: 2.5 s with no kick -> kick watchdog faults. */
    plat_host_advance_ns(2500000000ULL);
    tc_poll(&tc);
    printf("    state %s, fault %s\n", tc_state_name(tc_state(&tc)),
           tc_fault_name(tc_fault(&tc)));
    CHECK(tc_state(&tc) == TC_STATE_FAULT, "missed kick faults the run");
    CHECK(tc_fault(&tc) == TC_FAULT_WATCHDOG_KICK, "fault code");
    CHECK(plat_release_get() == false, "output driven safe");
}

/* ------------------------------------------------------------------ */
/* 6. Monitored stop: latches, ignores edges, needs deliberate reset. */
/* ------------------------------------------------------------------ */
static void test_estop(void) {
    printf("[6] Monitored stop (E-stop) latching\n");
    tc_t tc;
    tc_config_t cfg = base_cfg();
    tc_init(&tc, &cfg);
    plat_host_set_estop(false);
    plat_host_set_time_ns(1000000000ULL);
    tc_arm(&tc);
    tc_release(&tc);
    feed_edges(&tc, 38.1 / 20.0, 10, 1.25, 0, 0, 0);

    plat_host_set_estop(true); /* physical stop pressed */
    tc_poll(&tc);
    CHECK(tc_state(&tc) == TC_STATE_ESTOP, "stop latches");
    CHECK(plat_release_get() == false, "output driven safe");

    plat_host_set_estop(false); /* button released again */
    tc_poll(&tc);
    CHECK(tc_state(&tc) == TC_STATE_ESTOP, "stop stays latched");

    tc_result_t before;
    tc_get_result(&tc, &before);
    feed_edges(&tc, 38.1 / 20.0, 5, 20.0, 0, 0, 0);
    tc_result_t after;
    tc_get_result(&tc, &after);
    CHECK(after.edges_accepted == before.edges_accepted,
          "edges ignored while stopped");
    CHECK(tc_release(&tc) == TC_ERR_STATE, "no resume from stop");
    CHECK(tc_reset(&tc) == TC_OK && tc_state(&tc) == TC_STATE_IDLE,
          "deliberate reset to idle");
    CHECK(tc_arm(&tc) == TC_OK && tc_release(&tc) == TC_OK &&
              tc_state(&tc) == TC_STATE_RELEASED,
          "controller reusable after reset");
}

/* ------------------------------------------------------------------ */
/* 7. Plausibility window: impossibly fast cycles fault the run.     */
/* ------------------------------------------------------------------ */
static void test_period_window(void) {
    printf("[7] Plausibility window: period below the minimum\n");
    tc_t tc;
    tc_config_t cfg = base_cfg();
    cfg.min_period_ns = 1600000000ULL; /* 1.6 s */
    cfg.max_period_ns = 2200000000ULL; /* 2.2 s */
    tc_init(&tc, &cfg);
    plat_host_set_estop(false);
    plat_host_set_time_ns(0);
    tc_arm(&tc);
    tc_release(&tc);
    feed_edges(&tc, 1.2, 3, 0.25, 0, 0, 0); /* 1.2 s cycles: too fast */

    printf("    state %s, fault %s\n", tc_state_name(tc_state(&tc)),
           tc_fault_name(tc_fault(&tc)));
    CHECK(tc_state(&tc) == TC_STATE_FAULT, "out-of-window period faults");
    CHECK(tc_fault(&tc) == TC_FAULT_PERIOD_WINDOW, "fault code");
    CHECK(plat_release_get() == false, "output driven safe");
}

/* ------------------------------------------------------------------ */
/* 8. Configuration validation.                                       */
/* ------------------------------------------------------------------ */
static void test_config_validation(void) {
    printf("[8] Configuration validation\n");
    tc_t tc;
    tc_config_t cfg = base_cfg();
    cfg.target_cycles = 0;
    CHECK(tc_init(&tc, &cfg) == TC_ERR_CONFIG, "zero target rejected");
    cfg = base_cfg();
    cfg.edges_per_cycle = 0;
    CHECK(tc_init(&tc, &cfg) == TC_ERR_CONFIG, "zero edges/cycle rejected");
    cfg = base_cfg();
    cfg.min_period_ns = 3000000000ULL;
    cfg.max_period_ns = 1000000000ULL;
    CHECK(tc_init(&tc, &cfg) == TC_ERR_CONFIG, "inverted window rejected");
    cfg = base_cfg();
    CHECK(tc_init(&tc, &cfg) == TC_OK, "valid config accepted");
}

int main(void) {
    printf("Mimforge timing controller - host test harness\n");
    printf("(host build, virtual clock; NOT a QNX build - see README)\n\n");
    test_worked_example();
    test_jitter();
    test_glitch_rejection();
    test_watchdog_edge_gap();
    test_watchdog_kick();
    test_estop();
    test_period_window();
    test_config_validation();
    printf("\n%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
