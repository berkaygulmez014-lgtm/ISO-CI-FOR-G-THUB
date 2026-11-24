# Parametral OS — build and test entry points
PYTHON ?= python3
CC     ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror
BIN     = bin

.PHONY: all guard test proof clean doctor oracle smoke sign

all: guard

guard: $(BIN)/seccomp_guard

$(BIN)/seccomp_guard: src/parametral_guard.c
	@mkdir -p $(BIN)
	@$(CC) $(CFLAGS) -static -o $@ $< 2>/dev/null || \
	 $(CC) $(CFLAGS) -o $@ $<
	@echo "built $@"

test: guard
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

proof: guard
	PYTHONPATH=src $(PYTHON) -m parametral.cli proof

oracle: guard
	@test -f "$$HOME/.local/state/parametral/operator.key" || PYTHONPATH=src $(PYTHON) -m parametral.cli harddeny keygen

sign: guard
	PYTHONPATH=src $(PYTHON) -m parametral.cli harddeny sign

smoke: guard
	bash scripts/smoke.sh

doctor: guard
	PYTHONPATH=src $(PYTHON) -m parametral.cli doctor

clean:
	rm -f $(BIN)/seccomp_guard
	rm -rf proofs/isolation-proof.txt
