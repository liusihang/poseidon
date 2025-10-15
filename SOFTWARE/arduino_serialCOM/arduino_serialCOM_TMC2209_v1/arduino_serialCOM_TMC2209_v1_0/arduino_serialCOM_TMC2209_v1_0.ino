/*
  Poseidon Pumps — CSV frame firmware (UNO + CNC Shield v3, TMC2209 STEP/DIR, no UART)
  本版：ROLE=SECONDARY 时，将 P4 映射到 Z 轴（Z_STEP=D4, Z_DIR=D7）

  协议（同前）：
    <SETTING,SPEED,1,1200,F,0,0,0>
    <SETTING,ACCEL,2,4000,F,0,0,0>
    <SETTING,DELTA,1,800,F,0,0,0>
    <RUN,DIST,13,0.0,F,4000,0,4000,0>
    <STOP,BLAH,123,BLAH,F,0,0,0,0>
    <PAUSE,BLAH,12,BLAH,F,0,0,0,0>
    <RESUME,BLAH,12,BLAH,F,0,0,0,0>
    <ZERO,BLAH,BLAH,BLAH,F,0,0,0,0>

  ACK（余步）：
    <p1_d2g,p2_d2g,p3_d2g,p4_d2g>
*/
#include <AccelStepper.h>
#include <string.h>
#include <stdlib.h>

// ===== 角色选择 =====
#define BOARD_ROLE_PRIMARY 0   // ★ 本版默认副板：0=SECONDARY(P3/P4)，1=PRIMARY(P1/P2)

// ===== 引脚映射（UNO + CNC Shield v3）=====
#define EN_PIN   8   // 低电平使能（TMC2209 ENN）
#define X_STP    2
#define X_DIR    5
#define Y_STP    3
#define Y_DIR    6
#define Z_STP    4   // ★ 将 P4 切换到 Z：STEP=D4
#define Z_DIR    7   // ★ 将 P4 切换到 Z：DIR =D7

// ===== 串口波特率 =====
#define BAUD_RATE 230400

// ===== 运动默认参数（步/秒、步/秒²）=====
#define DEFAULT_VMAX   500.0f
#define DEFAULT_ACCEL  500.0f

// ===== TMC2209 STEP 时序 =====
#define MIN_PULSE_US   3   // 安全 3us 脉宽

// ===== 主动上报/空闲断能 =====
#define STAT_INTERVAL_MS 200
#define IDLE_DISABLE_MS  500

static bool     driversOn     = false;
static uint32_t lastMotionMs  = 0;
static uint32_t lastStatMs    = 0;
static bool     prevActive    = false;

static inline void enableDrivers(bool on){
  digitalWrite(EN_PIN, on ? LOW : HIGH);
  driversOn = on;
}

// ===== 电机对象 =====
AccelStepper stepperX(AccelStepper::DRIVER, X_STP, X_DIR);
AccelStepper stepperY(AccelStepper::DRIVER, Y_STP, Y_DIR);
AccelStepper stepperZ(AccelStepper::DRIVER, Z_STP, Z_DIR);
AccelStepper* S[3] = { &stepperX, &stepperY, &stepperZ };  // 0:X 1:Y 2:Z

// ===== 串口帧缓冲 =====
static const int BUF_SZ = 128;
char frameBuf[BUF_SZ];
int  frameLen = 0;
bool inFrame  = false;

// ===== 工具函数 =====
static inline long d2gPump(int pump){
#if BOARD_ROLE_PRIMARY
  if (pump==1) return stepperX.distanceToGo();
  if (pump==2) return stepperY.distanceToGo();
  return 0;
#else
  if (pump==3) return stepperX.distanceToGo(); // SECONDARY: P3->X
  if (pump==4) return stepperZ.distanceToGo(); // SECONDARY: P4->Z ★
  return 0;
#endif
}

static inline void replyD2G(){
  Serial.print('<');
  Serial.print(d2gPump(1)); Serial.print(',');
  Serial.print(d2gPump(2)); Serial.print(',');
  Serial.print(d2gPump(3)); Serial.print(',');
  Serial.print(d2gPump(4)); Serial.print('>');
}

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

AccelStepper* axisOfPump(int pump){
#if BOARD_ROLE_PRIMARY
  if (pump==1) return &stepperX;
  if (pump==2) return &stepperY;
  return nullptr;
#else
  if (pump==3) return &stepperX; // P3->X
  if (pump==4) return &stepperZ; // P4->Z ★
  return nullptr;
#endif
}

// 去空白+转大写，取首字符（保证 DIR 稳定解析）
static inline char firstNonSpaceUpper(const char* s){
  while (*s==' ' || *s=='\t') ++s;
  char c = *s ? *s : 'F';
  if (c>='a' && c<='z') c -= 32;
  return c;
}

// ===== 执行器 =====
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
  int  sign0  = (dir=='B')? -1 : 1;
  enableDrivers(true);
  for (int p=1; p<=4; ++p){
    if (!(pumpsMask & (1<<(p-1)))) continue;
    AccelStepper* a = axisOfPump(p);
    if (!a) continue;
    long rel = sign0 * arr[p-1];
    a->move(rel);
  }
  replyD2G();
}

void exec_STOP(uint8_t pumpsMask){
  for (int p=1; p<=4; ++p){
    if (!(pumpsMask & (1<<(p-1)))) continue;
    AccelStepper* a = axisOfPump(p);
    if (!a) continue;
    a->stop();
  }
  replyD2G();
}

void exec_ZERO(){
  stepperX.setCurrentPosition(0);
  stepperY.setCurrentPosition(0);
  stepperZ.setCurrentPosition(0); // ★ 一并清零，兼容 P4->Z
  replyD2G();
}

// PAUSE 等价 STOP；RESUME 仅 ACK
void exec_PAUSE(uint8_t pumpsMask){ exec_STOP(pumpsMask); }
void exec_RESUME(uint8_t /*pumpsMask*/){ replyD2G(); }

// ===== 解析与分派 =====
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
  char    DIR   = (n>4 && tok[4]) ? firstNonSpaceUpper(tok[4]) : 'F';
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

// ===== Arduino 入口 =====
void setup(){
  Serial.begin(BAUD_RATE);
  pinMode(EN_PIN, OUTPUT);
  enableDrivers(false);

  for (int i=0;i<3;++i){
    S[i]->setMaxSpeed(DEFAULT_VMAX);
    S[i]->setAcceleration(DEFAULT_ACCEL);
    S[i]->setMinPulseWidth(MIN_PULSE_US);
  }

  pinMode(LED_BUILTIN, OUTPUT);
  for (int i=0;i<3;++i){ digitalWrite(LED_BUILTIN,HIGH); delay(80); digitalWrite(LED_BUILTIN,LOW); delay(80); }
#if BOARD_ROLE_PRIMARY
  Serial.println(F("FW READY (CSV,230400,TMC2209-STEP/DIR,ROLE=PRIMARY P1->X,P2->Y)"));
#else
  Serial.println(F("FW READY (CSV,230400,TMC2209-STEP/DIR,ROLE=SECONDARY P3->X,P4->Z)"));
#endif

  lastMotionMs = millis();
  lastStatMs   = millis();
  prevActive   = false;
}

void loop(){
  // 推进
  stepperX.run();
  stepperY.run();
  stepperZ.run();

  bool active = false;
  if (stepperX.distanceToGo() != 0 || stepperX.speed() != 0.0f) active = true;
  if (stepperY.distanceToGo() != 0 || stepperY.speed() != 0.0f) active = true;
  if (stepperZ.distanceToGo() != 0 || stepperZ.speed() != 0.0f) active = true;

  uint32_t now = millis();
  if (active) {
    lastMotionMs = now;
    if (now - lastStatMs >= STAT_INTERVAL_MS) {
      replyD2G();
      lastStatMs = now;
    }
  } else {
    if (prevActive) { replyD2G(); lastStatMs = now; }
    if (driversOn && (now - lastMotionMs) >= IDLE_DISABLE_MS) enableDrivers(false);
  }
  prevActive = active;

  // 串口接收
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
