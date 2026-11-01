# The Simple-Train throttle for the Commodore 64 Ultimate.
#   make          builds simple-train-c64.prg (needs cc65: sudo apt install cc65)
#   make test     runs the protocol tests on this computer (needs gcc)
# SERVER_IP sets the PC address the program suggests, e.g.
#   make SERVER_IP=192.168.1.201

SERVER_IP ?= 192.168.1.201
PRG = simple-train-c64.prg
SOURCES = src/main.c src/wt.c src/uci.c
SCRATCH ?= build

all: $(PRG)

$(PRG): $(SOURCES) src/wt.h src/uci.h src/ascii.h
	mkdir -p $(SCRATCH)
	cl65 -t c64 -O -Or -Cl -DSERVER_IP='"$(SERVER_IP)"' -o $@ $(SOURCES)

test: $(SCRATCH)/test_wt
	$(SCRATCH)/test_wt

$(SCRATCH)/test_wt: tests/test_wt.c src/wt.c src/wt.h
	mkdir -p $(SCRATCH)
	cc -Wall -Wextra -Wno-unknown-pragmas -std=c99 -o $@ tests/test_wt.c src/wt.c

clean:
	rm -rf $(SCRATCH) $(PRG)

.PHONY: all test clean
