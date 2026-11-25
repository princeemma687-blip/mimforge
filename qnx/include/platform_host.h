/*
 * platform_host.h - test hooks for the host platform implementation.
 *
 * These functions exist ONLY in src/platform_host.c (the host build).
 * They let a test harness drive the virtual clock and the simulated
 * stop input deterministically. They are never part of a target build.
 */
#ifndef MIMFORGE_PLATFORM_HOST_H
#define MIMFORGE_PLATFORM_HOST_H

#include <stdbool.h>
#include <stdint.h>

/* Set the virtual clock to an absolute time in nanoseconds. */
void plat_host_set_time_ns(uint64_t t_ns);

/* Advance the virtual clock by a relative amount in nanoseconds. */
void plat_host_advance_ns(uint64_t delta_ns);

/* Drive the simulated hardware stop input read by plat_estop_requested(). */
void plat_host_set_estop(bool requested);

#endif /* MIMFORGE_PLATFORM_HOST_H */
