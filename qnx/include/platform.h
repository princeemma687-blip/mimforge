/*
 * platform.h - Mimforge timing controller: platform abstraction layer (PAL).
 *
 * The timing controller core (timing_controller.c) contains NO platform
 * calls other than the five functions declared here. Retargeting the
 * controller from the host build to QNX SDP 8.0 (or to a microcontroller
 * board) is a platform-file swap:
 *
 *   host build   -> src/platform_host.c   (virtual clock, simulated I/O)
 *   QNX 8.0      -> src/platform_qnx.c    (ClockCycles(), board I/O)
 *
 * Nothing in this header is specific to any one practical or machine:
 * the controller is a generic cycle-timing / counting engine.
 */
#ifndef MIMFORGE_PLATFORM_H
#define MIMFORGE_PLATFORM_H

#include <stdbool.h>
#include <stdint.h>

/* Monotonic clock in nanoseconds. Must never run backwards and must not
 * be affected by wall-clock adjustments. On QNX this is derived from
 * ClockCycles(); on the host it is a controllable virtual clock. */
uint64_t plat_now_ns(void);

/* Release / trigger actuator output. on=true energises the release
 * mechanism; on=false returns it to its safe (de-energised) state.
 * The controller drives this off on completion, fault and stop. */
void plat_release_set(bool on);

/* Last state commanded through plat_release_set(). Lets tests and
 * monitoring confirm the output really was driven safe. */
bool plat_release_get(void);

/* Hardware stop request (e.g. a physical latching stop button wired to
 * an input). Polled by the controller; a true reading latches the
 * monitored-stop state. The controller also exposes tc_estop() for
 * software-initiated stops through the same path. */
bool plat_estop_requested(void);

/* Diagnostic logging sink. printf-style. On the host this writes to
 * stdout; on target it writes to the console / system logger. */
void plat_log(const char *fmt, ...);

#endif /* MIMFORGE_PLATFORM_H */
