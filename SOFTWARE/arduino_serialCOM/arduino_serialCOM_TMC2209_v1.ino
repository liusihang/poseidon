#include <AccelStepper.h>
#include <TMC2209Stepper.h>  // 引入 TMC2209 驱动库
#include <string.h>
#include <stdlib.h>

// =================== 角色选择（主/副板）===================
#define BOARD_ROLE_PRIMARY 1  // 1=主板(P1/P2)；0=副板(P3/P4)

// =================== 引脚映射（UNO + CNC Shield v3）======
#define EN_PIN   8   // 低电平使能
#define X_STP    2
#define X_DIR    5
#define Y_STP    3
#define Y_DIR    6
#define Z_STP    4
#define Z_DIR    7

// TMC2209 驱动控制引脚
#define DIR_PIN   5
#define STEP_PIN  2
#define ENABLE_PIN 8
#define SERIAL_PORT  Serial1  // 使用 Serial1，适应 TMC2209 的 UART 通信

#define R_SENSE 0.11f // TMC2209 的电流感应电阻（根据具体模块调整）

#define BAUD_RATE 230400  // 更改波特率为 230400

// =================== 运动默认参数（保守稳健）=============
#define DEFAULT_VMAX   400.0f   // steps/s
#define DEFAULT_ACCEL  300.0f   // steps/s^2
#define MIN_PULSE_US   2        // DRV8825 ≥1.9us

// =================== 主动状态上报/空闲断电参数 ============
#define STAT_INTERVAL_MS 200    // 5 Hz 主动上报余步
#define IDLE_DISABLE_MS  500    // 静止超过该时间自动断使能

static bool     driversOn     = false;
static uint32_t lastMotionMs  = 0;
static uint32_t lastStatMs    = 0;
static bool     prevActive    = false;

// TMC2209 驱动器实例化
TMC2209Stepper driver(&SERIAL_PORT, R_SENSE);  // 使用 UART 连接 TMC2209

// 统一的驱动使能控制（低电平=上电使能）
static inline void enableDrivers(bool on){
  if (on) {
    digitalWrite(ENABLE_PIN, LOW);  // 使能驱动
    driversOn = true;
  } else {
    digitalWrite(ENABLE_PIN, HIGH); // 断开驱动
    driversOn = false;
  }
}

// =================== 电机对象 ============================
AccelStepper stepperX(AccelStepper::DRIVER, X_STP, X_DIR);
AccelStepper stepperY(AccelStepper::DRIVER, Y_STP, Y_DIR);
AccelStepper stepperZ(AccelStepper::DRIVER, Z_STP, Z_DIR); // 预留
AccelStepper* S[3] = { &stepperX, &stepperY, &stepperZ };  // 0:X 1:Y 2:Z

// =================== 串口帧缓冲 ==========================
static const int BUF_SZ = 128;
char frameBuf[BUF_SZ];
int  frameLen = 0;
bool inFrame  = false;

// =================== 小工具 ===============================
static inline long d2gPump(int pump){
#if BOARD_ROLE_PRIMARY
  if (pump==1) return stepperX.distanceToGo();
  if (pump==2) return stepperY.distanceToGo();
  return 0; // 忽略 P3/P4
#else
  if (pump==3) return stepperX.distanceToGo();
  if (pump==4) return stepperY.distanceToGo();
  return 0; // 忽略 P1/P2
#endif
}

static inline void replyD2G(){
  Serial.print('<');
  Serial.print(d2gPump(1)); Serial.print(',');
  Serial.print(d2gPump(2)); Serial.print(',');
  Serial.print(d2gPump(3)); Serial.print(',');
  Serial.print(d2gPump(4)); Serial.print('>');
}

// 解析 pumps 字符串为位掩码，例如 "13" -> bit0、bit2 置位
uint8_t parsePumpsMask(const char* s){
  uint8_t m=0;
  for (const char* p=s; *p; ++p){
    if (*p=='1') m|= (1<<0);
    else if (*p=='2') m|= (1<<1);
    else if (*p=='3') m|= (1<<2);
    else if (*p=='4') m|= (1<<3);
  }
  return m;
}

// pump 编号→本板实际轴；不在本板的返回 nullptr
AccelStepper* axisOfPump(int pump){
#if BOARD_ROLE_PRIMARY
  if (pump==1) return &stepperX;
  if (pump==2) return &stepperY;
  return nullptr;
#else
  if (pump==3) return &stepperX;
  if (pump==4) return &stepperY;
  return nullptr;
#endif
}

// =================== 执行器 ===============================
void exec_SETTING_SPEED(uint8_t pumpsMask, float v){
  if (v<=0) v=DEFAULT_VMAX;
  for (int p=1; p<=4; ++p){
    if (!(pumpsMask & (1<<(p-1)))) continue;
    AccelStepper* a = axisOfPump(p);
    if (!a) continue;
    a->setMaxSpeed(v);
  }
  replyD2G();
}

void exec_SETTING_ACCEL(uint8_t pumpsMask, float aVal){
  if (aVal<=0) aVal=DEFAULT_ACCEL;
  for (int p=1; p<=4; ++p){
    if (!(pumpsMask & (1<<(p-1)))) continue;
    AccelStepper* a = axisOfPump(p);
    if (!a) continue;
    a->setAcceleration(aVal);
  }
  replyD2G();
}

void exec_SETTING_DELTA(uint8_t /*pumpsMask*/, float /*delta*/){
  replyD2G();
}

void exec_RUN_DIST(uint8_t pumpsMask, char dir, long p1,long p2,long p3,long p4){
  long arr[4] = {p1,p2,p3,p4};
  int  sign   = (dir=='B')? -1 : 1;

  // 开始运动：上电
  enableDrivers(true);

  for (int p=1; p<=4; ++p){
    if (!(pumpsMask & (1<<(p-1)))) continue;
    AccelStepper* a = axisOfPump(p);
    if (!a) continue;
    long rel = sign * arr[p-1];
    a->move(rel);  // 非阻塞；loop() 推进
  }
  replyD2G();
}

void exec_STOP(uint8_t pumpsMask){
  for (int p=1; p<=4; ++p){
    if (!(pumpsMask & (1<<(p-1)))) continue;
    AccelStepper* a = axisOfPump(p);
    if (!a) continue;
    a->stop();      // 按加速度平滑停
  }
  replyD2G();
}

void exec_ZERO(){
  stepperX.setCurrentPosition(0);
  stepperY.setCurrentPosition(0);
  replyD2G();
}

void exec_PAUSE(uint8_t pumpsMask){
  exec_STOP(pumpsMask);
}

void exec_RESUME(uint8_t /*pumpsMask*/){
  replyD2G();
}

// =================== CSV 解析与分派 =======================
void parseAndExec(char* buf){
  const int MAXT=12;
  char* tok[MAXT]; int n=0;
  char* save = nullptr;
  char* p = strtok_r(buf, ",", &save);
  while (p && n<MAXT){ tok[n++]=p; p=strtok_r(nullptr, ",", &save); }
  if (n<1) { replyD2G(); return; }

  auto upcase = [](char* s){ for(char* q=s; *q; ++q){ if(*q>='a'&&*q<='z') *q-=32; } };
  upcase(tok[0]);                      // MODE
  if (n>1 && tok[1]) upcase(tok[1]);  // SETTING

  const char* MODE  = tok[0];
  const char* SETT  = (n>1)? tok[1] : "";
  const char* PUMPS = (n>2)? tok[2] : "0";
  uint8_t pumpsMask = parsePumpsMask(PUMPS);
  float   VAL   = (n>3)? atof(tok[3]) : 0.0f;
  char    DIR   = (n>4 && tok[4] && tok[4][0]) ? tok[4][0] : 'F';
  long    PVAL[4]={0,0,0,0};
  if (n>5) PVAL[0]=atol(tok[5]);
  if (n>6) PVAL[1]=atol(tok[6]);
  if (n>7) PVAL[2]=atol(tok[7]);
  if (n>8) PVAL[3]=atol(tok[8]);

  if (strcmp(MODE,"RUN")==0 && strcmp(SETT,"DIST")==0) { exec_RUN_DIST(pumpsMask, DIR, PVAL[0],PVAL[1],PVAL[2],PVAL[3]); return; }
  if (strcmp(MODE,"SETTING")==0){
    if (strcmp(SETT,"SPEED")==0) { exec_SETTING_SPEED(pumpsMask, VAL); return; }
    if (strcmp(SETT,"ACCEL")==0) { exec_SETTING_ACCEL(pumpsMask, VAL); return; }
    if (strcmp(SETT,"DELTA")==0) { exec_SETTING_DELTA(pumpsMask, VAL); return; }
  }
  if (strcmp(MODE,"STOP")==0)   { exec_STOP(pumpsMask); return; }
  if (strcmp(MODE,"PAUSE")==0)  { exec_PAUSE(pumpsMask); return; }
  if (strcmp(MODE,"RESUME")==0) { exec_RESUME(pumpsMask); return; }
  if (strcmp(MODE,"ZERO")==0)   { exec_ZERO(); return; }

  replyD2G();
}

// =================== Arduino 入口 =========================
void setup(){
  SERIAL_PORT.begin(BAUD_RATE);  // 使用新的波特率 230400
  pinMode(EN_PIN, OUTPUT);
  enableDrivers(false);               // 上电默认失能（安全）

  for (int i=0;i<3;++i){
    S[i]->setMaxSpeed(DEFAULT_VMAX);
    S[i]->setAcceleration(DEFAULT_ACCEL);
    S[i]->setMinPulseWidth(MIN_PULSE_US);
  }

  pinMode(LED_BUILTIN, OUTPUT);
  for (int i=0;i<3;++i){ digitalWrite(LED_BUILTIN,HIGH); delay(80); digitalWrite(LED_BUILTIN,LOW); delay(80); }
  Serial.println(F("FW READY (CSV,230400)")); // 显示新波特率

  lastMotionMs = millis();
  lastStatMs   = millis();
  prevActive   = false;
}

void loop(){
  // 推进电机（非阻塞）
  stepperX.run();
  stepperY.run();
  stepperZ.run();

  // === 是否有运动 ===
  bool active = false;
  if (stepperX.distanceToGo() != 0 || stepperX.speed() != 0.0f) active = true;
  if (stepperY.distanceToGo() != 0 || stepperY.speed() != 0.0f) active = true;
  if (stepperZ.distanceToGo() != 0 || stepperZ.speed() != 0.0f) active = true;

  uint32_t now = millis();

  if (active) {
    lastMotionMs = now;

    // 5 Hz 主动上报
    if (now - lastStatMs >= STAT_INTERVAL_MS) {
      replyD2G();
      lastStatMs = now;
    }

  } else {
    // 由运动->静止：立即上报一次（确保归零及时）
    if (prevActive) {
      replyD2G();
      lastStatMs = now;
    }
    // 静止超过阈值后自动断使能
    if (driversOn && (now - lastMotionMs) >= IDLE_DISABLE_MS) {
      enableDrivers(false);
    }
  }

  prevActive = active;

  // 串口接收状态机
  while (Serial.available()>0){
    char c = Serial.read();
    if (!inFrame){
      if (c=='<'){ inFrame=true; frameLen=0; }
    }else{
      if (c=='>'){
        frameBuf[frameLen]=0;
        inFrame=false;
        parseAndExec(frameBuf);
      }else{
        if (frameLen < BUF_SZ-1) frameBuf[frameLen++] = c;
      }
    }
  }
}
