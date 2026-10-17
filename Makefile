# Standalone macOS arm64 build for the USD-free Python binding.
# Run with Python 3.12 and pybind11 headers installed; see README.md.
.DEFAULT_GOAL := all
PACKMAN_PYTHON := $(firstword $(wildcard .packman-cache/python/3.12.*-macos-aarch64/bin/python3.12))
PYTHON ?= $(if $(PACKMAN_PYTHON),$(PACKMAN_PYTHON),python3.12)
PYBIND11_INCLUDE ?= .deps/pybind11/pybind11/include
PYTHON_INCLUDE := $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("include"))')
EXT_SUFFIX := $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')
CXX := clang++
BUILD_DIR := .build/smlib-core
SMLIB_SRC := $(wildcard usd-brep/source/SMLib/src/*.cpp)
SMAPI_SRC := $(wildcard usd-brep/source/SM_API/src/*.cpp)
SMLIB_OBJ := $(patsubst usd-brep/source/SMLib/src/%.cpp,$(BUILD_DIR)/SMLib/%.o,$(SMLIB_SRC))
SMAPI_OBJ := $(patsubst usd-brep/source/SM_API/src/%.cpp,$(BUILD_DIR)/SM_API/%.o,$(SMAPI_SRC))
CORE_OBJ := $(BUILD_DIR)/SmPyCore.o
OUTPUT := $(BUILD_DIR)/_smlib_core$(EXT_SUFFIX)
INCLUDES := -Iusd-brep/source/SMLib/inc -Iusd-brep/source/SM_API/inc -I$(PYTHON_INCLUDE) -I$(PYBIND11_INCLUDE)
CXXFLAGS := -std=c++17 -O1 -fPIC -arch arm64 -MMD -MP -Wno-inconsistent-missing-override -Wno-overloaded-virtual -Wno-unused-but-set-variable -Wno-unused-variable -Wno-parentheses-equality -Wno-deprecated-literal-operator
MODEL ?= model.json
PORT ?= 8765
HOST ?= 0.0.0.0
CERT_DIR ?= .certs

-include $(SMLIB_OBJ:.o=.d) $(SMAPI_OBJ:.o=.d) $(CORE_OBJ:.o=.d)

.PHONY: all clean glb usdz start start-http start-https cert
all: $(OUTPUT)

start: start-https

start-http: $(OUTPUT)
	@PYTHONPATH="$(abspath $(BUILD_DIR)):$$PYTHONPATH" $(PYTHON) server.py --host $(HOST) --port $(PORT)

cert:
	@$(PYTHON) local_cert.py --dir "$(CERT_DIR)" $(if $(CERT_IP),--ip "$(CERT_IP)")

start-https: $(OUTPUT) cert
	@PYTHONPATH="$(abspath $(BUILD_DIR)):$$PYTHONPATH" $(PYTHON) server.py --host $(HOST) --port $(PORT) --cert "$(CERT_DIR)/server.crt" --key "$(CERT_DIR)/server.key"

glb: $(OUTPUT)
	@$(PYTHON) json_to_glb.py "$(MODEL)" $(if $(GLB),-o "$(GLB)")

usdz: $(OUTPUT)
	@$(PYTHON) json_to_usdz.py "$(MODEL)" $(if $(USDZ),-o "$(USDZ)")

$(BUILD_DIR)/SMLib/%.o: usd-brep/source/SMLib/src/%.cpp
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -c $< -o $@

$(BUILD_DIR)/SM_API/%.o: usd-brep/source/SM_API/src/%.cpp
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -DSM_API_EXPORTS -c $< -o $@

$(CORE_OBJ): usd-brep/source/SmPyCore/src/SmPyCore.cpp
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -c $< -o $@

$(OUTPUT): $(SMLIB_OBJ) $(SMAPI_OBJ) $(CORE_OBJ)
	$(CXX) -bundle -undefined dynamic_lookup -arch arm64 $^ -o $@

clean:
	rm -rf $(BUILD_DIR)
