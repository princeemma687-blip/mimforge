/*
 * timing_controller.c - generic real-time timing / counting controller.
 *
 * Platform-independent: the only external calls are the five PAL
 * functions in platform.h. See timing_controller.h for the contract.
 *
 * Supervision model: the owning loop calls tc_kick() once per
 * iteration and tc_poll() once per iteration. tc_poll() performs the
 * stop-input and watchdog checks; it deliberately does NOT refresh the
 * kick timestamp itself, otherwise a loop that only polled could never
 * trip the kick deadline.
 */
#include "timing_controller.h"

#include <string.h>

#include "platform.h"

static void drive_output_safe(void) { plat_release_set(false); }

static void enter_fault(tc_t *tc, tc_fault_t fault, const char *why) {
    drive_output_safe();
    tc->fault = fault;
    tc->state = TC_STATE_FAULT;
    plat_log("timing_controller: FAULT %s (%s) after %u cycles",
             tc_fault_name(fault), why, (unsigned)tc->cycles_completed);
}

tc_status_t tc_init(tc_t *tc, const tc_config_t *cfg) {
    if (tc == NULL || cfg == NULL) return TC_ERR_CONFIG;
    if (cfg->target_cycles == 0 || cfg->edges_per_cycle == 0)
        return TC_ERR_CONFIG;
    if (cfg->min_period_ns != 0 && cfg->max_period_ns != 0 &&
        cfg->min_period_ns > cfg->max_period_ns)
        return TC_ERR_CONFIG;

    memset(tc, 0, sizeof(*tc));
    tc->cfg = *cfg;
    tc->state = TC_STATE_IDLE;
    tc->fault = TC_FAULT_NONE;
    return TC_OK;
}

tc_status_t tc_arm(tc_t *tc) {
    if (tc->state != TC_STATE_IDLE && tc->state != TC_STATE_COMPLETE)
        return TC_ERR_STATE;

    tc_config_t cfg = tc->cfg;
    memset(tc, 0, sizeof(*tc));
    tc->cfg = cfg;
    tc->state = TC_STATE_ARMED;
    tc->fault = TC_FAULT_NONE;
    plat_log("timing_controller: armed (target %u cycles, %u edges/cycle)",
             (unsigned)cfg.target_cycles, (unsigned)cfg.edges_per_cycle);
    return TC_OK;
}

tc_status_t tc_release(tc_t *tc) {
    if (tc->state != TC_STATE_ARMED) return TC_ERR_STATE;

    tc->release_ns = plat_now_ns();
    tc->last_kick_ns = tc->release_ns;
    plat_release_set(true);
    tc->state = TC_STATE_RELEASED;
    plat_log("timing_controller: released at %llu ns",
             (unsigned long long)tc->release_ns);
    return TC_OK;
}

void tc_on_sensor_edge(tc_t *tc) {
    if (tc->state != TC_STATE_RELEASED && tc->state != TC_STATE_RUNNING)
        return; /* edges outside a run are ignored by design */

    uint64_t now = plat_now_ns();

    /* Glitch / bounce rejection: an edge implausibly soon after the
     * previous accepted edge cannot be a real cycle event. */
    if (tc->edges_accepted > 0 && tc->cfg.min_edge_interval_ns > 0 &&
        (now - tc->last_edge_ns) < tc->cfg.min_edge_interval_ns) {
        tc->edges_rejected++;
        return;
    }

    tc->edges_accepted++;
    tc->last_edge_ns = now;

    if (tc->state == TC_STATE_RELEASED) {
        /* First accepted edge starts the timing. */
        tc->first_edge_ns = now;
        tc->cycle_start_ns = now;
        tc->edges_in_cycle = 0;
        tc->state = TC_STATE_RUNNING;
        return;
    }

    /* RUNNING: accumulate edges toward a complete cycle. */
    tc->edges_in_cycle++;
    if (tc->edges_in_cycle < tc->cfg.edges_per_cycle) return;

    uint64_t period_ns = now - tc->cycle_start_ns;
    tc->edges_in_cycle = 0;
    tc->cycle_start_ns = now;
    if (tc->periods_count < TC_MAX_RECORDED_CYCLES)
        tc->periods_ns[tc->periods_count++] = period_ns;
    tc->cycles_completed++;

    /* Plausibility window: bad data faults the run rather than being
     * silently recorded (checked before completion on purpose). */
    if ((tc->cfg.min_period_ns != 0 && period_ns < tc->cfg.min_period_ns) ||
        (tc->cfg.max_period_ns != 0 && period_ns > tc->cfg.max_period_ns)) {
        enter_fault(tc, TC_FAULT_PERIOD_WINDOW, "cycle period out of window");
        return;
    }

    if (tc->cycles_completed >= tc->cfg.target_cycles) {
        drive_output_safe();
        tc->state = TC_STATE_COMPLETE;
        plat_log("timing_controller: complete, %u cycles in %llu ns",
                 (unsigned)tc->cycles_completed,
                 (unsigned long long)(tc->last_edge_ns - tc->first_edge_ns));
    }
}

void tc_kick(tc_t *tc) { tc->last_kick_ns = plat_now_ns(); }

void tc_poll(tc_t *tc) {
    /* Monitored stop has priority over every other check. */
    if (plat_estop_requested()) {
        if (tc->state != TC_STATE_ESTOP) tc_estop(tc);
        return;
    }

    if (tc->state != TC_STATE_RELEASED && tc->state != TC_STATE_RUNNING)
        return;

    uint64_t now = plat_now_ns();

    if (tc->cfg.watchdog_timeout_ns > 0) {
        uint64_t base = (tc->edges_accepted > 0) ? tc->last_edge_ns
                                                 : tc->release_ns;
        if (now - base > tc->cfg.watchdog_timeout_ns) {
            enter_fault(tc, TC_FAULT_WATCHDOG_EDGE_GAP,
                        "no sensor edge within watchdog timeout");
            return;
        }
    }

    if (tc->cfg.kick_deadline_ns > 0 &&
        now - tc->last_kick_ns > tc->cfg.kick_deadline_ns) {
        enter_fault(tc, TC_FAULT_WATCHDOG_KICK,
                    "supervising loop missed its kick deadline");
        return;
    }
}

void tc_estop(tc_t *tc) {
    drive_output_safe();
    if (tc->state != TC_STATE_ESTOP) {
        tc->state = TC_STATE_ESTOP;
        plat_log("timing_controller: monitored stop latched");
    }
}

tc_status_t tc_reset(tc_t *tc) {
    if (tc->state != TC_STATE_ESTOP && tc->state != TC_STATE_FAULT &&
        tc->state != TC_STATE_COMPLETE)
        return TC_ERR_STATE;
    tc->state = TC_STATE_IDLE;
    tc->fault = TC_FAULT_NONE;
    plat_log("timing_controller: reset to idle");
    return TC_OK;
}

void tc_get_result(const tc_t *tc, tc_result_t *out) {
    memset(out, 0, sizeof(*out));
    out->cycles_completed = tc->cycles_completed;
    out->edges_accepted = tc->edges_accepted;
    out->edges_rejected = tc->edges_rejected;

    if (tc->edges_accepted > 0) {
        out->elapsed_ns = tc->last_edge_ns - tc->first_edge_ns;
        out->release_to_first_edge_ns = tc->first_edge_ns - tc->release_ns;
    }

    if (tc->periods_count > 0) {
        uint64_t sum = 0, mn = UINT64_MAX, mx = 0;
        for (uint32_t i = 0; i < tc->periods_count; i++) {
            uint64_t p = tc->periods_ns[i];
            sum += p;
            if (p < mn) mn = p;
            if (p > mx) mx = p;
        }
        double mean = (double)sum / (double)tc->periods_count;
        double jitter = 0.0;
        for (uint32_t i = 0; i < tc->periods_count; i++) {
            double d = (double)tc->periods_ns[i] - mean;
            if (d < 0) d = -d;
            if (d > jitter) jitter = d;
        }
        out->mean_period_s = mean / 1e9;
        out->min_period_s = (double)mn / 1e9;
        out->max_period_s = (double)mx / 1e9;
        out->jitter_s = jitter / 1e9;
    }
}

tc_state_t tc_state(const tc_t *tc) { return tc->state; }
tc_fault_t tc_fault(const tc_t *tc) { return tc->fault; }

const char *tc_state_name(tc_state_t s) {
    switch (s) {
        case TC_STATE_IDLE: return "IDLE";
        case TC_STATE_ARMED: return "ARMED";
        case TC_STATE_RELEASED: return "RELEASED";
        case TC_STATE_RUNNING: return "RUNNING";
        case TC_STATE_COMPLETE: return "COMPLETE";
        case TC_STATE_ESTOP: return "ESTOP";
        case TC_STATE_FAULT: return "FAULT";
    }
    return "?";
}

const char *tc_fault_name(tc_fault_t f) {
    switch (f) {
        case TC_FAULT_NONE: return "NONE";
        case TC_FAULT_WATCHDOG_EDGE_GAP: return "WATCHDOG_EDGE_GAP";
        case TC_FAULT_WATCHDOG_KICK: return "WATCHDOG_KICK";
        case TC_FAULT_PERIOD_WINDOW: return "PERIOD_WINDOW";
    }
    return "?";
}
