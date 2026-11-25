/*
 * timing_controller.h - generic real-time timing / counting controller.
 *
 * A reusable engine for machine steps of the form:
 *
 *     arm -> release (trigger) -> count sensor edges for N complete
 *     cycles while measuring each cycle's period with a high-resolution
 *     monotonic clock -> report counts, elapsed time and period
 *     statistics.
 *
 * The controller knows nothing about what is being timed. A cycle is
 * defined purely by configuration: `edges_per_cycle` accepted sensor
 * edges make one cycle (e.g. 2 for a gate placed at a symmetry point of
 * an oscillating mechanism, 1 for a once-per-revolution marker).
 *
 * Safety behaviour built in, per the project safety design:
 *   - Watchdog: if accepted edges stop arriving while a run is active
 *     (gap > watchdog_timeout_ns), or the supervising loop stops kicking
 *     (gap > kick_deadline_ns), the controller faults and drives the
 *     release output safe.
 *   - Monitored stop: a hardware stop input (polled) or tc_estop()
 *     latches the ESTOP state from ANY state; the release output is
 *     driven safe and sensor edges are ignored until a deliberate
 *     tc_reset() returns the controller to IDLE. A stop never resumes
 *     a run automatically.
 *   - Plausibility window: a completed cycle whose period falls outside
 *     [min_period_ns, max_period_ns] faults the run instead of silently
 *     recording bad data.
 *   - Glitch rejection: edges arriving sooner than min_edge_interval_ns
 *     after the previous accepted edge are counted as rejected and do
 *     not affect timing.
 *
 * All timestamps are read from the platform clock (plat_now_ns()) at
 * the moment each entry point is called, so on target the sensor-edge
 * path should be called directly from the interrupt / high-priority
 * polling context that observes the edge.
 */
#ifndef MIMFORGE_TIMING_CONTROLLER_H
#define MIMFORGE_TIMING_CONTROLLER_H

#include <stdbool.h>
#include <stdint.h>

#define TC_MAX_RECORDED_CYCLES 128u

typedef enum {
    TC_STATE_IDLE = 0,   /* reset and waiting to be armed              */
    TC_STATE_ARMED,      /* configured, waiting for the release trigger */
    TC_STATE_RELEASED,   /* release fired, waiting for the first edge   */
    TC_STATE_RUNNING,    /* counting cycles                             */
    TC_STATE_COMPLETE,   /* target cycles measured; results available   */
    TC_STATE_ESTOP,      /* monitored stop latched; deliberate reset req */
    TC_STATE_FAULT       /* watchdog / plausibility fault; reset req    */
} tc_state_t;

typedef enum {
    TC_FAULT_NONE = 0,
    TC_FAULT_WATCHDOG_EDGE_GAP, /* no accepted edge within the timeout   */
    TC_FAULT_WATCHDOG_KICK,     /* supervising loop stopped kicking      */
    TC_FAULT_PERIOD_WINDOW      /* cycle period outside the allowed band */
} tc_fault_t;

typedef enum {
    TC_OK = 0,
    TC_ERR_STATE,  /* call not valid in the current state */
    TC_ERR_CONFIG  /* invalid configuration               */
} tc_status_t;

typedef struct {
    uint32_t target_cycles;        /* complete cycles to time (> 0)      */
    uint32_t edges_per_cycle;      /* accepted edges per cycle (> 0)     */
    uint64_t min_edge_interval_ns; /* bounce/glitch rejection; 0 = off   */
    uint64_t min_period_ns;        /* plausibility window; 0 = no lower  */
    uint64_t max_period_ns;        /* plausibility window; 0 = no upper  */
    uint64_t watchdog_timeout_ns;  /* max edge gap while active; 0 = off */
    uint64_t kick_deadline_ns;     /* max kick gap while active; 0 = off */
} tc_config_t;

typedef struct {
    tc_state_t state;
    tc_fault_t fault;

    tc_config_t cfg;

    /* Run bookkeeping. */
    uint32_t edges_in_cycle;    /* accepted edges in the current cycle  */
    uint32_t cycles_completed;
    uint32_t edges_accepted;
    uint32_t edges_rejected;    /* glitches rejected by the interval rule */
    uint64_t release_ns;        /* when the release was commanded       */
    uint64_t first_edge_ns;     /* first accepted edge (timing start)   */
    uint64_t last_edge_ns;      /* most recent accepted edge            */
    uint64_t cycle_start_ns;    /* start edge of the current cycle      */
    uint64_t last_kick_ns;      /* most recent watchdog kick            */

    /* Per-cycle period history (nanoseconds), oldest first. */
    uint64_t periods_ns[TC_MAX_RECORDED_CYCLES];
    uint32_t periods_count;
} tc_t;

typedef struct {
    uint32_t cycles_completed;
    uint32_t edges_accepted;
    uint32_t edges_rejected;
    uint64_t elapsed_ns;              /* last edge - first edge          */
    uint64_t release_to_first_edge_ns;
    double mean_period_s;
    double min_period_s;
    double max_period_s;
    double jitter_s;                  /* max |period - mean period|      */
} tc_result_t;

/* Initialise a controller with a configuration. Returns TC_ERR_CONFIG
 * if target_cycles or edges_per_cycle is zero, or if a plausibility
 * window is inverted. Leaves the controller in TC_STATE_IDLE. */
tc_status_t tc_init(tc_t *tc, const tc_config_t *cfg);

/* IDLE or COMPLETE -> ARMED. Clears all run counters and results. */
tc_status_t tc_arm(tc_t *tc);

/* ARMED -> RELEASED. Commands the release output on and stamps the
 * release time. Timing itself starts at the first accepted edge. */
tc_status_t tc_release(tc_t *tc);

/* Feed one sensor edge. Valid in RELEASED and RUNNING; in any other
 * state the edge is ignored (and, in ESTOP/FAULT, deliberately so).
 * Applies glitch rejection, cycle counting, per-cycle period recording
 * and the plausibility window. Reaching target_cycles completes the
 * run and drives the release output safe. */
void tc_on_sensor_edge(tc_t *tc);

/* Watchdog kick from the supervising loop. The loop supervising the
 * controller must call this (or tc_poll) regularly; see tc_poll. */
void tc_kick(tc_t *tc);

/* Periodic supervision. The supervising loop calls tc_kick() once
 * per iteration and tc_poll() once per iteration.
 * - Honours the hardware stop input (plat_estop_requested()).
 * - Enforces the edge-gap watchdog and the kick deadline while a run
 *   is active (RELEASED or RUNNING).
 * tc_poll() deliberately does NOT refresh the kick timestamp: a loop
 * that only polled, without kicking, must still trip the deadline. */
void tc_poll(tc_t *tc);

/* Monitored stop. Valid from ANY state: latches ESTOP, drives the
 * release output safe. Only tc_reset() clears it, and reset goes to
 * IDLE - never back into a run. */
void tc_estop(tc_t *tc);

/* ESTOP, FAULT or COMPLETE -> IDLE. The deliberate human reset action. */
tc_status_t tc_reset(tc_t *tc);

/* Fill a results summary. Valid in any state; fields are meaningful
 * once at least one cycle has completed, and final in COMPLETE. */
void tc_get_result(const tc_t *tc, tc_result_t *out);

tc_state_t tc_state(const tc_t *tc);
tc_fault_t tc_fault(const tc_t *tc);
const char *tc_state_name(tc_state_t s);
const char *tc_fault_name(tc_fault_t f);

#endif /* MIMFORGE_TIMING_CONTROLLER_H */
