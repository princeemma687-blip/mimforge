/*
 * platform_qnx.c - QNX Neutrino 8.0 implementation of the platform
 * abstraction layer.
 *
 * !!! NOT COMPILED OR RUN YET !!!
 * QNX SDP 8.0 is not installed on the development machine used for the
 * host build, and obtaining it requires a myQNX account registration
 * that is deliberately left to the project owner. This file is written
 * against the documented QNX 8.0 API so that the target build is a
 * platform-file swap (see Makefile.qnx), but it has never been compiled
 * - treat it as a reviewed draft, not verified code. The whole file is
 * guarded by __QNXNTO__ so host builds ignore it entirely.
 *
 * Target wiring notes (x86_64 under QEMU first, real board later):
 *   - Clock: ClockCycles() scaled by the syspage cycles-per-second.
 *   - Release output: on the QEMU target there is no physical actuator;
 *     the output state is kept in memory and logged, which is enough to
 *     exercise the full controller. On real hardware, plat_release_set()
 *     is where the board's GPIO / driver write goes (marked TODO).
 *   - Stop input: a high-priority thread or interrupt handler sets
 *     g_estop_requested via plat_qnx_raise_estop(); the controller's
 *     poll path latches it. On real hardware this is fed by the
 *     physical latching stop button input (marked TODO).
 */
#ifdef __QNXNTO__

#include <inttypes.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

#include "platform.h"

static bool g_release_on = false;
static volatile bool g_estop_requested = false;

uint64_t plat_now_ns(void) {
    uint64_t cycles = ClockCycles();
    uint64_t cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
    if (cps == 0) return 0;
    /* Split the multiply to stay overflow-safe for long uptimes. */
    return (cycles / cps) * 1000000000ULL +
           (cycles % cps) * 1000000000ULL / cps;
}

void plat_release_set(bool on) {
    g_release_on = on;
    /* TODO(board): write the release actuator GPIO / device here.
     * Under QEMU this is intentionally state-only + logged. */
    plat_log("release output -> %s", on ? "ON" : "OFF (safe)");
}

bool plat_release_get(void) { return g_release_on; }

bool plat_estop_requested(void) { return g_estop_requested; }

/* Called by the stop-input interrupt handler / monitor thread. */
void plat_qnx_raise_estop(void) { g_estop_requested = true; }
void plat_qnx_clear_estop(void) { g_estop_requested = false; }

void plat_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
}

#endif /* __QNXNTO__ */
