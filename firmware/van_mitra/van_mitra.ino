/* =============================================================================
 *  AI Van Mitra - button / presence / LED bridge (Arduino Nano or ESP32)
 *
 *  Sends to the Mac (USB serial, 115200 baud), one line per event:
 *      BTN_DOWN  BTN_UP  PRESENCE_ON  PRESENCE_OFF
 *  Receives from the Mac:
 *      LED:IDLE  LED:GREETING  LED:READY  LED:LISTENING  LED:THINKING  LED:SPEAKING
 *
 *  Wiring
 *    D2  <- 60 mm arcade button (other leg to GND; internal pull-up, pressed = LOW)
 *    D3  <- LD2410 mmWave sensor OUT pin (HIGH = person present)
 *    D6  -> WS2812 LED ring DIN (330 ohm series resistor; 1000 uF across 5 V near the ring)
 *    5 V / GND from the 12 V -> 5 V SMPS (common ground with the Arduino)
 *
 *  Library: Adafruit NeoPixel (Library Manager)
 * ============================================================================= */
#include <Adafruit_NeoPixel.h>

const uint8_t PIN_BUTTON = 2;
const uint8_t PIN_PRESENCE = 3;
const uint8_t PIN_LEDS = 6;
const uint8_t NUM_LEDS = 16;

const unsigned long DEBOUNCE_MS = 30;     // button must be stable this long
const unsigned long PRESENCE_MS = 1000;   // sensor must be stable this long

Adafruit_NeoPixel ring(NUM_LEDS, PIN_LEDS, NEO_GRB + NEO_KHZ800);

enum LedMode { M_IDLE, M_READY, M_LISTENING, M_THINKING, M_SPEAKING };
LedMode mode = M_IDLE;

bool btnStable = false, btnLastRead = false;
unsigned long btnChangedAt = 0;
bool presStable = false, presLastRead = false;
unsigned long presChangedAt = 0;
String rx;

void setup() {
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_PRESENCE, INPUT);
  Serial.begin(115200);
  ring.begin();
  ring.setBrightness(110);
  ring.show();
}

void loop() {
  unsigned long now = millis();

  // ---- button with debounce
  bool b = digitalRead(PIN_BUTTON) == LOW;
  if (b != btnLastRead) { btnLastRead = b; btnChangedAt = now; }
  if (b != btnStable && now - btnChangedAt >= DEBOUNCE_MS) {
    btnStable = b;
    Serial.println(b ? "BTN_DOWN" : "BTN_UP");
  }

  // ---- presence with 1 s stability (ignores flicker)
  bool p = digitalRead(PIN_PRESENCE) == HIGH;
  if (p != presLastRead) { presLastRead = p; presChangedAt = now; }
  if (p != presStable && now - presChangedAt >= PRESENCE_MS) {
    presStable = p;
    Serial.println(p ? "PRESENCE_ON" : "PRESENCE_OFF");
  }

  // ---- commands from the Mac
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (rx.startsWith("LED:")) setMode(rx.substring(4));
      rx = "";
    } else if (rx.length() < 32) {
      rx += c;
    }
  }

  drawLeds(now);
}

void setMode(const String &s) {
  if (s == "IDLE") mode = M_IDLE;
  else if (s == "READY" || s == "GREETING") mode = M_READY;
  else if (s == "LISTENING") mode = M_LISTENING;
  else if (s == "THINKING") mode = M_THINKING;
  else if (s == "SPEAKING") mode = M_SPEAKING;
}

void fill(uint8_t r, uint8_t g, uint8_t b, float k) {
  for (uint8_t i = 0; i < NUM_LEDS; i++) ring.setPixelColor(i, ring.Color(r * k, g * k, b * k));
}

void drawLeds(unsigned long now) {
  static unsigned long last = 0;
  if (now - last < 20) return;              // ~50 fps
  last = now;
  float t = now / 1000.0;
  switch (mode) {
    case M_IDLE:      fill(40, 160, 60, 0.15 + 0.15 * (1 + sin(t * 2.0)) / 2); break;     // slow soft green breathing
    case M_READY:     fill(60, 220, 80, 0.45 + 0.35 * (1 + sin(t * 4.0)) / 2); break;     // green, "press me"
    case M_LISTENING: fill(40, 120, 255, 1.0); break;                                     // solid blue
    case M_SPEAKING:  fill(60, 220, 80, 0.7); break;                                      // steady green
    case M_THINKING: {                                                                    // amber spinner
      ring.clear();
      int head = (int)(t * 16) % NUM_LEDS;
      for (int k = 0; k < 5; k++) {
        float f = 1.0 - k * 0.2;
        ring.setPixelColor((head - k + NUM_LEDS) % NUM_LEDS, ring.Color(255 * f, 150 * f, 0));
      }
      break;
    }
  }
  ring.show();
}
