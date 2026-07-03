#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

// Arduino Mega 2560 pin map for a breadboarded AT28C256.
// Data bit n uses DATA_PINS[n]. Address bit n uses ADDR_PINS[n].
static const uint8_t DATA_PINS[8] = {43, 45, 47, 46, 44, 42, 40, 38};
static const uint8_t ADDR_PINS[15] = {41, 39, 37, 35, 33, 31, 29, 27, 26, 28, 34, 30, 25, 24, 23};

static const uint8_t PIN_CE = 36; // AT28C256 pin 20, active low
static const uint8_t PIN_OE = 32; // AT28C256 pin 22, active low
static const uint8_t PIN_WE = 22; // AT28C256 pin 27, active low

static const uint16_t EEPROM_SIZE = 32768;
static const unsigned long WRITE_TIMEOUT_MS = 50;

static char line[192];
static uint8_t lineLen = 0;

static void idleBus() {
  digitalWrite(PIN_WE, HIGH);
  digitalWrite(PIN_OE, HIGH);
  digitalWrite(PIN_CE, HIGH);
}

static void setDataInput() {
  for (uint8_t i = 0; i < 8; ++i) {
    pinMode(DATA_PINS[i], INPUT);
  }
}

static void setDataOutput(uint8_t value) {
  for (uint8_t i = 0; i < 8; ++i) {
    pinMode(DATA_PINS[i], OUTPUT);
    digitalWrite(DATA_PINS[i], (value >> i) & 1U);
  }
}

static void setAddress(uint16_t address) {
  for (uint8_t i = 0; i < 15; ++i) {
    digitalWrite(ADDR_PINS[i], (address >> i) & 1U);
  }
}

static uint8_t sampleDataBus() {
  uint8_t value = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    if (digitalRead(DATA_PINS[i])) {
      value |= (1U << i);
    }
  }
  return value;
}

static uint8_t readByte(uint16_t address) {
  idleBus();
  setDataInput();
  setAddress(address);
  digitalWrite(PIN_CE, LOW);
  digitalWrite(PIN_OE, LOW);
  delayMicroseconds(2);
  const uint8_t value = sampleDataBus();
  digitalWrite(PIN_OE, HIGH);
  digitalWrite(PIN_CE, HIGH);
  return value;
}

static bool writeByte(uint16_t address, uint8_t value) {
  idleBus();
  setAddress(address);
  setDataOutput(value);

  digitalWrite(PIN_CE, LOW);
  delayMicroseconds(1);
  digitalWrite(PIN_WE, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_WE, HIGH);
  delayMicroseconds(1);
  digitalWrite(PIN_CE, HIGH);

  setDataInput();

  const unsigned long start = millis();
  while (millis() - start < WRITE_TIMEOUT_MS) {
    if (readByte(address) == value) {
      return true;
    }
    delay(1);
  }
  return readByte(address) == value;
}

static bool parseNumber(const char *text, uint16_t maxValue, uint16_t *out) {
  if (text == nullptr || *text == '\0') {
    return false;
  }

  char *end = nullptr;
  unsigned long value = 0;

  if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
    value = strtoul(text + 2, &end, 16);
  } else {
    bool hasHexLetter = false;
    for (const char *p = text; *p; ++p) {
      if (isalpha(static_cast<unsigned char>(*p))) {
        hasHexLetter = true;
        break;
      }
    }
    value = strtoul(text, &end, hasHexLetter ? 16 : 10);
  }

  if (end == text || *end != '\0' || value > maxValue) {
    return false;
  }
  *out = static_cast<uint16_t>(value);
  return true;
}

static bool parseAddress(const char *text, uint16_t *out) {
  return parseNumber(text, EEPROM_SIZE - 1, out);
}

static bool parseByteValue(const char *text, uint8_t *out) {
  uint16_t value = 0;
  if (!parseNumber(text, 0xFF, &value)) {
    return false;
  }
  *out = static_cast<uint8_t>(value);
  return true;
}

static void printHex2(uint8_t value) {
  if (value < 0x10) {
    Serial.print('0');
  }
  Serial.print(value, HEX);
}

static void printHex4(uint16_t value) {
  if (value < 0x1000) Serial.print('0');
  if (value < 0x0100) Serial.print('0');
  if (value < 0x0010) Serial.print('0');
  Serial.print(value, HEX);
}

static void printHelp() {
  Serial.println(F("Commands:"));
  Serial.println(F("  ? | HELP                  Show this help"));
  Serial.println(F("  S                         Status and pin map"));
  Serial.println(F("  R <addr> [len]            Read bytes, compact hex"));
  Serial.println(F("  D <addr> [len]            Hex dump bytes"));
  Serial.println(F("  W <addr> <byte> [...]     Write byte(s)"));
  Serial.println(F("  V <addr> <byte> [...]     Verify byte(s)"));
  Serial.println(F("  F <addr> <len> <byte>     Fill range"));
  Serial.println(F("Examples:"));
  Serial.println(F("  W 0x0000 48 65 6C 6C 6F"));
  Serial.println(F("  R 0x0000 5"));
  Serial.println(F("  V 0x0000 48 65 6C 6C 6F"));
}

static void printStatus() {
  Serial.println(F("AT28C256 programmer status"));
  Serial.println(F("EEPROM: 32768 bytes, address range 0x0000-0x7FFF"));
  Serial.println(F("Data pins I/O0..I/O7: D22 D23 D24 D25 D26 D27 D28 D29"));
  Serial.println(F("Address pins A0..A14: D30 D31 D32 D33 D34 D35 D36 D37 D38 D39 D40 D41 D42 D43 D44"));
  Serial.println(F("Control: /CE=D45 /OE=D46 /WE=D47"));
  Serial.println(F("OK"));
}

static char *nextToken(char **context) {
  return strtok_r(nullptr, " \t,", context);
}

static void handleRead(char *context, bool dump) {
  char *addrText = nextToken(&context);
  char *lenText = nextToken(&context);
  uint16_t address = 0;
  uint16_t length = 1;

  if (!parseAddress(addrText, &address)) {
    Serial.println(F("ERR bad address"));
    return;
  }
  if (lenText != nullptr && !parseNumber(lenText, EEPROM_SIZE, &length)) {
    Serial.println(F("ERR bad length"));
    return;
  }
  if (length == 0 || static_cast<unsigned long>(address) + length > EEPROM_SIZE) {
    Serial.println(F("ERR range"));
    return;
  }

  if (!dump) {
    Serial.print(F("DATA "));
    printHex4(address);
    Serial.print(' ');
    for (uint16_t i = 0; i < length; ++i) {
      if (i) Serial.print(' ');
      printHex2(readByte(address + i));
    }
    Serial.println();
    Serial.println(F("OK"));
    return;
  }

  for (uint16_t offset = 0; offset < length; offset += 16) {
    const uint16_t rowAddress = address + offset;
    printHex4(rowAddress);
    Serial.print(F(": "));
    for (uint8_t i = 0; i < 16; ++i) {
      if (offset + i < length) {
        printHex2(readByte(rowAddress + i));
      } else {
        Serial.print(F("  "));
      }
      Serial.print(' ');
    }
    Serial.print(' ');
    for (uint8_t i = 0; i < 16 && offset + i < length; ++i) {
      const uint8_t b = readByte(rowAddress + i);
      Serial.print((b >= 32 && b <= 126) ? static_cast<char>(b) : '.');
    }
    Serial.println();
  }
  Serial.println(F("OK"));
}

static void handleWrite(char *context) {
  char *addrText = nextToken(&context);
  uint16_t address = 0;
  if (!parseAddress(addrText, &address)) {
    Serial.println(F("ERR bad address"));
    return;
  }

  uint16_t count = 0;
  char *byteText = nullptr;
  while ((byteText = nextToken(&context)) != nullptr) {
    if (address + count >= EEPROM_SIZE) {
      Serial.println(F("ERR range"));
      return;
    }
    uint8_t value = 0;
    if (!parseByteValue(byteText, &value)) {
      Serial.println(F("ERR bad byte"));
      return;
    }
    if (!writeByte(address + count, value)) {
      Serial.print(F("ERR write timeout at 0x"));
      printHex4(address + count);
      Serial.println();
      return;
    }
    ++count;
  }

  if (count == 0) {
    Serial.println(F("ERR no bytes"));
    return;
  }
  Serial.print(F("OK WROTE "));
  Serial.println(count);
}

static void handleVerify(char *context) {
  char *addrText = nextToken(&context);
  uint16_t address = 0;
  if (!parseAddress(addrText, &address)) {
    Serial.println(F("ERR bad address"));
    return;
  }

  uint16_t count = 0;
  char *byteText = nullptr;
  while ((byteText = nextToken(&context)) != nullptr) {
    if (address + count >= EEPROM_SIZE) {
      Serial.println(F("ERR range"));
      return;
    }
    uint8_t expected = 0;
    if (!parseByteValue(byteText, &expected)) {
      Serial.println(F("ERR bad byte"));
      return;
    }
    const uint8_t actual = readByte(address + count);
    if (actual != expected) {
      Serial.print(F("ERR VERIFY 0x"));
      printHex4(address + count);
      Serial.print(F(" expected 0x"));
      printHex2(expected);
      Serial.print(F(" got 0x"));
      printHex2(actual);
      Serial.println();
      return;
    }
    ++count;
  }

  if (count == 0) {
    Serial.println(F("ERR no bytes"));
    return;
  }
  Serial.print(F("OK VERIFIED "));
  Serial.println(count);
}

static void handleFill(char *context) {
  char *addrText = nextToken(&context);
  char *lenText = nextToken(&context);
  char *byteText = nextToken(&context);
  uint16_t address = 0;
  uint16_t length = 0;
  uint8_t value = 0;

  if (!parseAddress(addrText, &address)) {
    Serial.println(F("ERR bad address"));
    return;
  }
  if (!parseNumber(lenText, EEPROM_SIZE, &length) || length == 0) {
    Serial.println(F("ERR bad length"));
    return;
  }
  if (!parseByteValue(byteText, &value)) {
    Serial.println(F("ERR bad byte"));
    return;
  }
  if (static_cast<unsigned long>(address) + length > EEPROM_SIZE) {
    Serial.println(F("ERR range"));
    return;
  }

  for (uint16_t i = 0; i < length; ++i) {
    if (!writeByte(address + i, value)) {
      Serial.print(F("ERR write timeout at 0x"));
      printHex4(address + i);
      Serial.println();
      return;
    }
  }
  Serial.print(F("OK FILLED "));
  Serial.println(length);
}

static void handleCommand(char *cmdLine) {
  char *context = nullptr;
  char *cmd = strtok_r(cmdLine, " \t,", &context);
  if (cmd == nullptr) {
    Serial.print(F("> "));
    return;
  }

  for (char *p = cmd; *p; ++p) {
    *p = toupper(static_cast<unsigned char>(*p));
  }

  if (strcmp(cmd, "?") == 0 || strcmp(cmd, "HELP") == 0) {
    printHelp();
  } else if (strcmp(cmd, "S") == 0 || strcmp(cmd, "STATUS") == 0) {
    printStatus();
  } else if (strcmp(cmd, "R") == 0 || strcmp(cmd, "READ") == 0) {
    handleRead(context, false);
  } else if (strcmp(cmd, "D") == 0 || strcmp(cmd, "DUMP") == 0) {
    handleRead(context, true);
  } else if (strcmp(cmd, "W") == 0 || strcmp(cmd, "WRITE") == 0) {
    handleWrite(context);
  } else if (strcmp(cmd, "V") == 0 || strcmp(cmd, "VERIFY") == 0) {
    handleVerify(context);
  } else if (strcmp(cmd, "F") == 0 || strcmp(cmd, "FILL") == 0) {
    handleFill(context);
  } else {
    Serial.println(F("ERR unknown command; type ?"));
  }

  Serial.print(F("> "));
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_CE, OUTPUT);
  pinMode(PIN_OE, OUTPUT);
  pinMode(PIN_WE, OUTPUT);
  idleBus();

  for (uint8_t i = 0; i < 15; ++i) {
    pinMode(ADDR_PINS[i], OUTPUT);
    digitalWrite(ADDR_PINS[i], LOW);
  }
  setDataInput();

  Serial.println();
  Serial.println(F("AT28C256 programmer ready"));
  Serial.println(F("Type ? for help."));
  Serial.print(F("> "));
}

void loop() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    
    if(c == '\b' && lineLen != 0) {
      line[lineLen--] = 0;
      Serial.print("\b \b");
      continue;
    }

    Serial.print(c);
    
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      line[lineLen] = '\0';
      handleCommand(line);
      lineLen = 0;
    } else if (static_cast<size_t>(lineLen) + 1 < sizeof(line)) {
      line[lineLen++] = c;
    } else {
      lineLen = 0;
      Serial.println(F("ERR line too long"));
      Serial.print(F("> "));
    }
  }
}
