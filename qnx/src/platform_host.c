/*
 * platform_host.c - host implementation of the platform abstraction
 * layer, used by the host build and its test harness.
 *
 * The clock is VIRTUAL: it only moves when the harness sets or advances
 * it (plat_host_set_time_ns / plat_host_advance_ns). That makes every
 * timing test fully deterministic - measured values can be compared
 * against expected values to nanosecond precision, with no dependence
 * on how fast the host machine happens to schedule the test process.
 *
 * The release output and the stop input are simulated in memory so
 * tests can observe and drive them.
 */
#include <stdarg.h>
#include <stdio.h>

#include "platform.h"
#include "platform_host.h"

static uint64_t g_now_ns = 0;
static bool g_release_on = false;
static bool g_estop = false;

uint64_t plat_now_ns(void) { return g_now_ns; }

void plat_release_set(bool on) { g_release_on = on; }

bool plat_release_get(void) { return g_release_on; }

bool plat_estop_requested(void) { return g_estop; }

void plat_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    printf("    [plat] ");
    vprintf(fmt, ap);
    printf("\n");
    va_end(ap);
}

/* --- host-only test hooks (platform_host.h) --- */

void plat_host_set_time_ns(uint64_t t_ns) { g_now_ns = t_ns; }

void plat_host_advance_ns(uint64_t delta_ns) { g_now_ns += delta_ns; }

void plat_host_set_estop(bool requested) { g_estop = requested; }
