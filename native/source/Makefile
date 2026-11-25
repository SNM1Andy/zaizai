CXX ?= c++
CXXFLAGS ?= -O2 -Wall -Wextra -Werror -pedantic
LDFLAGS ?= -static
.PHONY: all check
all: cl pcgm-alpha pcgm-beta
cl: $(wildcard cl-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp native-projection.hpp
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) $(LDFLAGS) cl-src/cl.cpp -o $@
cl-native.o: $(wildcard cl-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp native-projection.hpp
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) -DCL_NATIVE_LIBRARY -c cl-src/cl.cpp -o $@
pcgm-alpha: $(wildcard pcgm-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp anchored-assets.hpp native-projection.hpp cl-native.o
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) $(LDFLAGS) '-DPCGM_BUILD_NAME="alpha"' pcgm-src/cl.cpp cl-native.o -o $@
pcgm-beta: $(wildcard pcgm-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp anchored-assets.hpp native-projection.hpp cl-native.o
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) $(LDFLAGS) '-DPCGM_BUILD_NAME="beta"' pcgm-src/cl.cpp cl-native.o -o $@
check: all sdk
	@set -e; for test in check-*.py; do echo "=== $$test ==="; python3 "$$test"; done
.PHONY: sdk
sdk: libcl_runtime.so cl-c-sdk-check
libcl_runtime.so: $(wildcard cl-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp native-projection.hpp cl-c-api.h cl-c-api.cpp cl-sdk.exports
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) -fPIC -fvisibility=hidden -shared -DCL_NATIVE_LIBRARY -Wl,--version-script=cl-sdk.exports cl-src/cl.cpp cl-c-api.cpp -o $@
cl-c-sdk-check: cl-c-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-c-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
sdk: cl-frozen-sdk-check
cl-frozen-sdk-check: cl-frozen-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-frozen-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
sdk: cl-live-sdk-check
cl-live-sdk-check: cl-live-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-live-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
sdk: cl-audit-consumer
cl-audit-consumer: cl-audit-consumer.cpp cl-c-api.h native-os.hpp libcl_runtime.so
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) cl-audit-consumer.cpp -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
sdk: cl-workspace-sdk-check
cl-workspace-sdk-check: cl-workspace-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-workspace-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
.PHONY: projection-check-build
projection-check-build: cl-projection-direct pcgm-projection-direct projection-kernel-check
check: projection-check-build
cl-projection-direct: $(wildcard cl-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp native-projection.hpp
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) $(LDFLAGS) -DCL_DIRECT_PROJECTION cl-src/cl.cpp -o $@
cl-native-projection-direct.o: $(wildcard cl-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp native-projection.hpp
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) -DCL_NATIVE_LIBRARY -DCL_DIRECT_PROJECTION -c cl-src/cl.cpp -o $@
pcgm-projection-direct: $(wildcard pcgm-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp anchored-assets.hpp native-projection.hpp cl-native-projection-direct.o
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) $(LDFLAGS) -DCL_DIRECT_PROJECTION '-DPCGM_BUILD_NAME="alpha"' pcgm-src/cl.cpp cl-native-projection-direct.o -o $@
projection-kernel-check: projection-kernel-check.cpp native-projection.hpp
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) projection-kernel-check.cpp -o $@
sdk: cl-projection-sdk-check
cl-projection-sdk-check: cl-projection-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-projection-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
sdk: cl-release-compare-sdk-check
cl-release-compare-sdk-check: cl-release-compare-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-release-compare-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
sdk: cl-additive-workspace-sdk-check
cl-additive-workspace-sdk-check: cl-additive-workspace-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-additive-workspace-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
sdk: cl-unit-conversion-sdk-check
cl-unit-conversion-sdk-check: cl-unit-conversion-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-unit-conversion-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
.PHONY: stage-offline
export PREFIX
stage-offline: all libcl_runtime.so libcl_memory.so
	@test -n "$${PREFIX}" || { echo "set PREFIX to a new absolute user-owned directory" >&2; exit 1; }
	@python3 distribution/stage-runtime.py stage "$${PREFIX}"
sdk: cl-cost-profile-sdk-check
cl-cost-profile-sdk-check: cl-cost-profile-sdk-check.c cl-c-api.h libcl_runtime.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-cost-profile-sdk-check.c -L. -lcl_runtime -Wl,-rpath,'$$ORIGIN' -o $@
.PHONY: memory-sdk
memory-sdk: libcl_memory.so
libcl_memory.so: $(wildcard cl-src/*) cl-native.hpp cl-text-symbol.hpp native-projection.hpp cl-c-api.h cl-c-api.cpp cl-memory.exports
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) -fPIC -fvisibility=hidden -shared -ffunction-sections -fdata-sections -DCL_NATIVE_LIBRARY -DCL_PORTABLE_MEMORY_CORE -Wl,--gc-sections -Wl,--version-script=cl-memory.exports cl-src/cl.cpp cl-c-api.cpp -o $@
memory-sdk: cl-memory-sdk-check
check: memory-sdk
cl-memory-sdk-check: cl-memory-sdk-check.c cl-memory-api.h cl-c-api.h libcl_memory.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-memory-sdk-check.c -L. -lcl_memory -Wl,-rpath,'$$ORIGIN' -o $@
memory-sdk: cl-workspace-memory-sdk-check
cl-workspace-memory-sdk-check: cl-workspace-sdk-check.c cl-c-api.h libcl_memory.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread -DCL_MEMORY_HEADERS_ONLY cl-workspace-sdk-check.c -L. -lcl_memory -Wl,-rpath,'$$ORIGIN' -o $@
memory-sdk: cl-transition-sdk-check
cl-transition-sdk-check: cl-transition-sdk-check.c cl-memory-api.h cl-c-api.h libcl_memory.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-transition-sdk-check.c -L. -lcl_memory -Wl,-rpath,'$$ORIGIN' -o $@
check: cl-projection-two-worker
cl-projection-two-worker: $(wildcard cl-src/*) cl-native.hpp cl-text-symbol.hpp native-os.hpp native-projection.hpp
	$(CXX) -std=c++20 -pthread $(CXXFLAGS) $(LDFLAGS) -DCL_RANK_TWO_WORKER_REFERENCE cl-src/cl.cpp -o $@
memory-sdk: cl-checkpoint-audit-sdk-check
cl-checkpoint-audit-sdk-check: cl-checkpoint-audit-sdk-check.c cl-memory-api.h cl-c-api.h libcl_memory.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-checkpoint-audit-sdk-check.c -L. -lcl_memory -Wl,-rpath,'$$ORIGIN' -o $@
memory-sdk: cl-unicode-sdk-check
cl-unicode-sdk-check: cl-unicode-sdk-check.c cl-memory-api.h cl-c-api.h libcl_memory.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-unicode-sdk-check.c -L. -lcl_memory -Wl,-rpath,'$$ORIGIN' -o $@
memory-sdk: cl-profile-rebuild-sdk-check
cl-profile-rebuild-sdk-check: cl-profile-rebuild-sdk-check.c cl-memory-api.h cl-c-api.h libcl_memory.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-profile-rebuild-sdk-check.c -L. -lcl_memory -Wl,-rpath,'$$ORIGIN' -o $@
memory-sdk: cl-prepared-workspace-sdk-check
cl-prepared-workspace-sdk-check: cl-prepared-workspace-sdk-check.c cl-memory-api.h cl-c-api.h libcl_memory.so
	$(CC) -std=c11 -Wall -Wextra -Werror -pthread cl-prepared-workspace-sdk-check.c -L. -lcl_memory -Wl,-rpath,'$$ORIGIN' -o $@
