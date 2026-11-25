# Makefile - host build for the Mimforge timing controller.
#
# Builds the generic controller core + host platform layer + test
# harness with the system gcc and runs the harness. This is the HOST
# build only: it proves the controller logic on Linux with a virtual
# clock. The QNX SDP 8.0 target build lives in Makefile.qnx and has
# NOT been run (no SDP installed; see README.md).
#
#   make        build the test harness
#   make test   build and run it
#   make clean

CC      ?= gcc
CFLAGS  ?= -std=c99 -Wall -Wextra -Werror -O2 -Iinclude
BUILD   := build
BIN     := $(BUILD)/test_timing_controller
SRC     := src/timing_controller.c src/platform_host.c
HDRS    := include/timing_controller.h include/platform.h include/platform_host.h

all: $(BIN)

$(BIN): $(SRC) tests/test_timing_controller.c $(HDRS) | $(BUILD)
	$(CC) $(CFLAGS) -o $@ $(SRC) tests/test_timing_controller.c -lm

$(BUILD):
	mkdir -p $(BUILD)

test: $(BIN)
	./$(BIN)

clean:
	rm -rf $(BUILD)

.PHONY: all test clean
