CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -std=c11
TARGET   = bin/nstask.exe
SRC      = main.c nstask.c sha256.c

all: $(TARGET)

$(TARGET): $(SRC) ns_task_format.h sha256.h
	@mkdir -p bin
	$(CC) $(CFLAGS) -o $(TARGET) $(SRC)

test: $(TARGET)
	./$(TARGET) selftest

clean:
	rm -rf bin

.PHONY: all test clean
