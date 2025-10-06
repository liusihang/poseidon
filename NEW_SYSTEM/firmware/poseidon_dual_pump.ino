#include <AccelStepper.h>
#include <EEPROM.h>

// =========================================
// Poseidon Dual-Board Pump Controller
// -------------------------------------
// Compile once per Arduino Uno board.
// Define BOARD_ROLE_PRIMARY as 1 for the
// primary controller (pumps 1 & 2) and 0
// for the secondary controller (pumps 3 & 4).
// =========================================

#ifndef BOARD_ROLE_PRIMARY
#define BOARD_ROLE_PRIMARY 1
#endif

// =================== Pinout (UNO + CNC Shield v3) ==================
static constexpr uint8_t EN_PIN   = 8;   // LOW = enable
static constexpr uint8_t X_STP    = 2;
static constexpr uint8_t X_DIR    = 5;
static constexpr uint8_t Y_STP    = 3;
static constexpr uint8_t Y_DIR    = 6;
static constexpr uint8_t Z_STP    = 4;   // unused but reserved
static constexpr uint8_t Z_DIR    = 7;

static constexpr long   BAUD_RATE    = 230400;
static constexpr float  DEFAULT_VMAX = 600.0f;    // steps / s
static constexpr float  DEFAULT_ACC  = 400.0f;    // steps / s^2
static constexpr uint16_t MIN_PULSE  = 2;         // microseconds
static constexpr uint16_t EEPROM_TAG = 0xAA55;

// =================== Pump Configuration ============================
struct PumpConfig {
  float maxSpeed;    // steps/s
  float accel;       // steps/s^2
  float stepsPerUL;  // steps per microlitre (calibration result)
};

struct PersistedConfig {
  uint16_t tag;
  PumpConfig pumps[2]; // per-board storage for the hosted pumps
};

static PumpConfig pumpConfig[2];

// =================== Stepper wrappers ==============================
AccelStepper stepperX(AccelStepper::DRIVER, X_STP, X_DIR);
AccelStepper stepperY(AccelStepper::DRIVER, Y_STP, Y_DIR);
AccelStepper stepperZ(AccelStepper::DRIVER, Z_STP, Z_DIR); // reserved
AccelStepper* const hostedSteppers[2] = { &stepperX, &stepperY };

static inline void enableDrivers(bool enable) {
  digitalWrite(EN_PIN, enable ? LOW : HIGH);
}

static inline uint8_t hostedPumpIndex(uint8_t pumpId) {
#if BOARD_ROLE_PRIMARY
  return (pumpId == 1) ? 0 : (pumpId == 2) ? 1 : 255;
#else
  return (pumpId == 3) ? 0 : (pumpId == 4) ? 1 : 255;
#endif
}

static inline long distanceToGoForPump(uint8_t pumpId) {
#if BOARD_ROLE_PRIMARY
  if (pumpId == 1) return stepperX.distanceToGo();
  if (pumpId == 2) return stepperY.distanceToGo();
  return 0;
#else
  if (pumpId == 3) return stepperX.distanceToGo();
  if (pumpId == 4) return stepperY.distanceToGo();
  return 0;
#endif
}

// =================== Utilities ====================================
static void sendAck(long p1, long p2, long p3, long p4) {
  Serial.print('<');
  Serial.print(p1); Serial.print(',');
  Serial.print(p2); Serial.print(',');
  Serial.print(p3); Serial.print(',');
  Serial.print(p4); Serial.print('>');
}

static void sendAckAll() {
  sendAck(distanceToGoForPump(1), distanceToGoForPump(2),
          distanceToGoForPump(3), distanceToGoForPump(4));
}

static uint8_t parsePumpMask(const char* pumps) {
  uint8_t mask = 0;
  for (const char* p = pumps; *p; ++p) {
    if (*p >= '1' && *p <= '4') {
      mask |= 1 << (static_cast<uint8_t>(*p - '1'));
    }
  }
  return mask;
}

static void applyConfigToStepper(uint8_t localIdx) {
  AccelStepper* stepper = hostedSteppers[localIdx];
  stepper->setMaxSpeed(pumpConfig[localIdx].maxSpeed);
  stepper->setAcceleration(pumpConfig[localIdx].accel);
  stepper->setMinPulseWidth(MIN_PULSE);
}

static void loadPersistedConfig() {
  PersistedConfig stored;
  EEPROM.get(0, stored);
  if (stored.tag != EEPROM_TAG) {
    for (uint8_t i = 0; i < 2; ++i) {
      pumpConfig[i].maxSpeed   = DEFAULT_VMAX;
      pumpConfig[i].accel      = DEFAULT_ACC;
      pumpConfig[i].stepsPerUL = 1.0f;
      applyConfigToStepper(i);
    }
    return;
  }
  for (uint8_t i = 0; i < 2; ++i) {
    pumpConfig[i] = stored.pumps[i];
    if (pumpConfig[i].maxSpeed <= 0) pumpConfig[i].maxSpeed = DEFAULT_VMAX;
    if (pumpConfig[i].accel    <= 0) pumpConfig[i].accel    = DEFAULT_ACC;
    if (pumpConfig[i].stepsPerUL <= 0) pumpConfig[i].stepsPerUL = 1.0f;
    applyConfigToStepper(i);
  }
}

static void savePersistedConfig() {
  PersistedConfig stored;
  stored.tag = EEPROM_TAG;
  for (uint8_t i = 0; i < 2; ++i) {
    stored.pumps[i] = pumpConfig[i];
  }
  EEPROM.put(0, stored);
}

// =================== Command Execution ============================
static void execSettingSpeed(uint8_t mask, float value) {
  if (value <= 0) value = DEFAULT_VMAX;
  for (uint8_t pump = 1; pump <= 4; ++pump) {
    if (!(mask & (1 << (pump - 1)))) continue;
    uint8_t localIdx = hostedPumpIndex(pump);
    if (localIdx > 1) continue;
    pumpConfig[localIdx].maxSpeed = value;
    applyConfigToStepper(localIdx);
  }
  savePersistedConfig();
  sendAckAll();
}

static void execSettingAccel(uint8_t mask, float value) {
  if (value <= 0) value = DEFAULT_ACC;
  for (uint8_t pump = 1; pump <= 4; ++pump) {
    if (!(mask & (1 << (pump - 1)))) continue;
    uint8_t localIdx = hostedPumpIndex(pump);
    if (localIdx > 1) continue;
    pumpConfig[localIdx].accel = value;
    applyConfigToStepper(localIdx);
  }
  savePersistedConfig();
  sendAckAll();
}

static void execSettingStepsPerUL(uint8_t mask, float value) {
  if (value <= 0) return sendAckAll();
  for (uint8_t pump = 1; pump <= 4; ++pump) {
    if (!(mask & (1 << (pump - 1)))) continue;
    uint8_t localIdx = hostedPumpIndex(pump);
    if (localIdx > 1) continue;
    pumpConfig[localIdx].stepsPerUL = value;
  }
  savePersistedConfig();
  sendAckAll();
}

static void execRunDist(uint8_t mask, char dir, long p1,long p2,long p3,long p4) {
  long payload[4] = {p1,p2,p3,p4};
  int8_t sign = (dir == 'B') ? -1 : 1;
  enableDrivers(true);
  for (uint8_t pump = 1; pump <= 4; ++pump) {
    if (!(mask & (1 << (pump - 1)))) continue;
    uint8_t localIdx = hostedPumpIndex(pump);
    if (localIdx > 1) continue;
    long relativeSteps = sign * payload[pump - 1];
    hostedSteppers[localIdx]->move(relativeSteps);
  }
  sendAckAll();
}

static void execRunVolume(uint8_t mask, char dir, float ul) {
  if (ul <= 0) return sendAckAll();
  long steps[4] = {0,0,0,0};
  for (uint8_t pump = 1; pump <= 4; ++pump) {
    if (!(mask & (1 << (pump - 1)))) continue;
    uint8_t localIdx = hostedPumpIndex(pump);
    if (localIdx > 1) continue;
    steps[pump - 1] = lroundf(pumpConfig[localIdx].stepsPerUL * ul);
  }
  execRunDist(mask, dir, steps[0], steps[1], steps[2], steps[3]);
}

static void execStop(uint8_t mask) {
  for (uint8_t pump = 1; pump <= 4; ++pump) {
    if (!(mask & (1 << (pump - 1)))) continue;
    uint8_t localIdx = hostedPumpIndex(pump);
    if (localIdx > 1) continue;
    hostedSteppers[localIdx]->stop();
  }
  sendAckAll();
}

static void execZero() {
  for (uint8_t i = 0; i < 2; ++i) {
    hostedSteppers[i]->setCurrentPosition(0);
  }
  sendAckAll();
}

// =================== CSV Parser ====================================
static constexpr size_t BUFFER_SIZE = 128;
static char frameBuffer[BUFFER_SIZE];
static size_t frameLen = 0;
static bool inFrame = false;

static void upcase(char* s) {
  for (; *s; ++s) {
    if (*s >= 'a' && *s <= 'z') *s -= 32;
  }
}

static void dispatchFrame(char* frame) {
  const uint8_t MAX_TOKENS = 12;
  char* tokens[MAX_TOKENS];
  uint8_t tokenCount = 0;
  char* savePtr = nullptr;
  char* tok = strtok_r(frame, ",", &savePtr);
  while (tok && tokenCount < MAX_TOKENS) {
    tokens[tokenCount++] = tok;
    tok = strtok_r(nullptr, ",", &savePtr);
  }

  if (tokenCount == 0) {
    sendAckAll();
    return;
  }

  upcase(tokens[0]);
  if (tokenCount > 1 && tokens[1]) upcase(tokens[1]);

  const char* mode   = tokens[0];
  const char* action = (tokenCount > 1) ? tokens[1] : "";
  const char* pumps  = (tokenCount > 2) ? tokens[2] : "";
  uint8_t pumpMask   = parsePumpMask(pumps);
  float value        = (tokenCount > 3) ? atof(tokens[3]) : 0.0f;
  char direction     = (tokenCount > 4 && tokens[4] && tokens[4][0]) ? tokens[4][0] : 'F';
  long pvals[4]      = {0,0,0,0};
  if (tokenCount > 5) pvals[0] = atol(tokens[5]);
  if (tokenCount > 6) pvals[1] = atol(tokens[6]);
  if (tokenCount > 7) pvals[2] = atol(tokens[7]);
  if (tokenCount > 8) pvals[3] = atol(tokens[8]);

  if (strcmp(mode, "SETTING") == 0) {
    if (strcmp(action, "SPEED") == 0) return execSettingSpeed(pumpMask, value);
    if (strcmp(action, "ACCEL") == 0) return execSettingAccel(pumpMask, value);
    if (strcmp(action, "STEPSPERUL") == 0) return execSettingStepsPerUL(pumpMask, value);
  }

  if (strcmp(mode, "RUN") == 0) {
    if (strcmp(action, "DIST") == 0) {
      return execRunDist(pumpMask, direction, pvals[0], pvals[1], pvals[2], pvals[3]);
    }
    if (strcmp(action, "VOLUME") == 0) {
      return execRunVolume(pumpMask, direction, value);
    }
  }

  if (strcmp(mode, "STOP") == 0)   return execStop(pumpMask);
  if (strcmp(mode, "PAUSE") == 0)  return execStop(pumpMask);
  if (strcmp(mode, "RESUME") == 0) return sendAckAll();
  if (strcmp(mode, "ZERO") == 0)   return execZero();

  sendAckAll();
}

// =================== Arduino lifecycle =============================
void setup() {
  Serial.begin(BAUD_RATE);
  pinMode(EN_PIN, OUTPUT);
  enableDrivers(false);

  for (uint8_t i = 0; i < 2; ++i) {
    hostedSteppers[i]->setMaxSpeed(DEFAULT_VMAX);
    hostedSteppers[i]->setAcceleration(DEFAULT_ACC);
    hostedSteppers[i]->setMinPulseWidth(MIN_PULSE);
  }

  loadPersistedConfig();

  pinMode(LED_BUILTIN, OUTPUT);
  for (uint8_t i = 0; i < 3; ++i) {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(60);
    digitalWrite(LED_BUILTIN, LOW);
    delay(60);
  }
  Serial.println(F("POSEIDON READY"));
}

void loop() {
  stepperX.run();
  stepperY.run();

  while (Serial.available() > 0) {
    const char c = Serial.read();
    if (!inFrame) {
      if (c == '<') {
        inFrame = true;
        frameLen = 0;
      }
    } else {
      if (c == '>') {
        frameBuffer[frameLen] = '\0';
        inFrame = false;
        dispatchFrame(frameBuffer);
      } else if (frameLen < BUFFER_SIZE - 1) {
        frameBuffer[frameLen++] = c;
      }
    }
  }
}
