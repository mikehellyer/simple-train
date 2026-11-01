/* See wt.h. */
#include <string.h>
#include "ascii.h"
#include "wt.h"

#define LF 10
#define CR 13
#define LINE_MAX 1400

struct wt_roster_entry wt_roster[WT_MAX_ROSTER];
unsigned char wt_roster_count;
struct wt_point wt_points[WT_MAX_POINTS];
unsigned char wt_point_count;

unsigned char wt_have_loco;
unsigned int wt_address;
unsigned char wt_long;
char wt_loco_name[WT_NAME];
unsigned char wt_speed;
unsigned char wt_emergency;
unsigned char wt_forward = 1;
unsigned long wt_functions;
char wt_labels[WT_LABELS][WT_LABEL];
char wt_alert[41];
unsigned char wt_changed;
unsigned char wt_hold;

void (*wt_send)(const char *line, unsigned int length);

static char line[LINE_MAX + 1];
static unsigned int line_length;
static char out[64];
static char key[8];          /* our loco's key, e.g. "L144" */

static const char ENTRY[] = "]\\[";
static const char FIELD[] = "}|{";
static const char PART[] = "<;>";

/* --- small helpers (no printf: it's big on the C64) --- */

static unsigned char put_number(char *to, unsigned int value)
{
    char digits[6];
    unsigned char count = 0, i;
    do {
        digits[count++] = '0' + value % 10;
        value /= 10;
    } while (value);
    for (i = 0; i < count; ++i) {
        to[i] = digits[count - 1 - i];
    }
    return count;
}

static unsigned int read_number(const char *from, const char **end)
{
    unsigned int value = 0;
    while (*from >= '0' && *from <= '9') {
        value = value * 10 + (*from - '0');
        ++from;
    }
    if (end) {
        *end = from;
    }
    return value;
}

static void copy_text(char *to, const char *from, unsigned int length, unsigned char room)
{
    if (length > (unsigned int)(room - 1)) {
        length = room - 1;
    }
    memcpy(to, from, length);
    to[length] = 0;
}

static void send_text(const char *text)
{
    unsigned int length = strlen(text);
    memcpy(out, text, length);
    out[length] = LF;
    wt_send(out, length + 1);
}

/* "M0A" + key + "<;>" ; returns the length written into out */
static unsigned char start_action(void)
{
    unsigned char length = 3, k = 0;
    out[0] = 'M';
    out[1] = '0';
    out[2] = 'A';
    while (key[k]) {
        out[length++] = key[k++];
    }
    memcpy(out + length, PART, 3);
    return length + 3;
}

static void finish(unsigned char length)
{
    out[length] = LF;
    wt_send(out, length + 1);
}

static void make_key(void)
{
    key[0] = wt_long ? 'L' : 'S';
    key[put_number(key + 1, wt_address) + 1] = 0;
}

/* Find `what` in [from, to); returns its start, or 0. */
static const char *find(const char *from, const char *to, const char *what)
{
    unsigned char size = strlen(what);
    while (from + size <= to) {
        if (memcmp(from, what, size) == 0) {
            return from;
        }
        ++from;
    }
    return 0;
}

/* --- reading what Simple-Train sends --- */

static void read_roster(const char *at, const char *end)
{
    const char *next, *field;
    wt_roster_count = 0;
    at = find(at, end, ENTRY);
    while (at && wt_roster_count < WT_MAX_ROSTER) {
        struct wt_roster_entry *entry = &wt_roster[wt_roster_count];
        at += 3;
        next = find(at, end, ENTRY);
        if (!next) {
            next = end;
        }
        field = find(at, next, FIELD);  /* name}|{address}|{L */
        if (!field) {
            break;
        }
        copy_text(entry->name, at, field - at, WT_NAME);
        entry->address = read_number(field + 3, &at);
        entry->is_long = (at + 3 < next && at[3] == 'L');
        ++wt_roster_count;
        at = next < end ? next : 0;
    }
    wt_changed |= WT_ROSTER;
}

static void read_points(const char *at, const char *end)
{
    const char *next, *first, *second;
    wt_point_count = 0;
    at = find(at, end, ENTRY);
    while (at && wt_point_count < WT_MAX_POINTS) {
        struct wt_point *point = &wt_points[wt_point_count];
        at += 3;
        next = find(at, end, ENTRY);
        if (!next) {
            next = end;
        }
        first = find(at, next, FIELD);   /* system}|{name}|{state */
        second = first ? find(first + 3, next, FIELD) : 0;
        if (!second) {
            break;
        }
        copy_text(point->system, at, first - at, sizeof(point->system));
        copy_text(point->name, first + 3, second - first - 3, WT_NAME);
        point->state = (unsigned char)read_number(second + 3, 0);
        ++wt_point_count;
        at = next < end ? next : 0;
    }
    wt_changed |= WT_POINTS;
}

static void read_point_change(const char *at, const char *end)
{
    unsigned char state = *at - '0', i;
    unsigned int length = end - at - 1;
    for (i = 0; i < wt_point_count; ++i) {
        if (strlen(wt_points[i].system) == length && memcmp(wt_points[i].system, at + 1, length) == 0) {
            wt_points[i].state = state;
            wt_changed |= WT_POINTS;
        }
    }
}

static void read_labels(const char *at, const char *end)
{
    unsigned char number = 0;
    const char *next;
    memset(wt_labels, 0, sizeof(wt_labels));
    at = find(at, end, ENTRY);
    while (at && number < WT_LABELS) {
        at += 3;
        next = find(at, end, ENTRY);
        if (!next) {
            break;
        }
        copy_text(wt_labels[number++], at, next - at, WT_LABEL);
        at = next;
    }
    wt_changed |= WT_FUNCS;
}

static void read_action(const char *at, const char *end)
{
    const char *after;
    unsigned int value;
    if (at >= end) {
        return;
    }
    switch (*at) {
    case 'V':
        if (wt_hold) {
            return;    /* our own change on its way back: the newer value is ours */
        }
        if (at[1] == '-') {
            wt_speed = 0;
            wt_emergency = 1;
        } else {
            value = read_number(at + 1, 0);
            wt_speed = value > 126 ? 126 : (unsigned char)value;
            wt_emergency = 0;
        }
        wt_changed |= WT_SPEED;
        break;
    case 'R':
        if (!wt_hold) {
            wt_forward = at[1] != '0';
            wt_changed |= WT_DIR;
        }
        break;
    case 'F':
        value = read_number(at + 2, &after);
        if (value < 29) {
            if (at[1] == '1') {
                wt_functions |= 1UL << value;
            } else {
                wt_functions &= ~(1UL << value);
            }
            wt_changed |= WT_FUNCS;
        }
        break;
    }
}

static void read_line(const char *at, unsigned int length)
{
    const char *end = at + length;
    const char *part;
    unsigned char key_length;
    if (length < 2) {
        return;
    }
    if (at[0] == 'R' && at[1] == 'L') {
        read_roster(at, end);
    } else if (length >= 3 && memcmp(at, "PTL", 3) == 0) {
        read_points(at, end);
    } else if (length >= 5 && memcmp(at, "PTA", 3) == 0) {
        read_point_change(at + 3, end);
    } else if ((at[0] == 'H' && (at[1] == 'M' || at[1] == 'm'))) {
        copy_text(wt_alert, at + 2, length - 2, sizeof(wt_alert));
        wt_changed |= WT_ALERT;
    } else if (at[0] == 'M' && at[1] == '0' && length > 3 && wt_have_loco) {
        key_length = strlen(key);
        if ((unsigned int)(length - 3) < key_length || memcmp(at + 3, key, key_length) != 0) {
            return;    /* about another loco */
        }
        part = at + 3 + key_length;
        if (part + 3 > end || memcmp(part, PART, 3) != 0) {
            return;
        }
        part += 3;
        if (at[2] == 'A') {
            read_action(part, end);
        } else if (at[2] == 'L') {
            read_labels(part, end);
        } else if (at[2] == '-') {
            wt_have_loco = 0;
            wt_changed |= WT_LOCO;
        }
    }
}

void wt_reset(void)
{
    wt_roster_count = 0;
    wt_point_count = 0;
    wt_have_loco = 0;
    wt_speed = 0;
    wt_emergency = 0;
    wt_forward = 1;
    wt_functions = 0;
    wt_alert[0] = 0;
    wt_hold = 0;
    line_length = 0;
    memset(wt_labels, 0, sizeof(wt_labels));
    wt_changed = 0xFF;
}

void wt_feed(const char *bytes, unsigned int length)
{
    unsigned int i;
    for (i = 0; i < length; ++i) {
        char c = bytes[i];
        if (c == LF || c == CR) {
            if (line_length) {
                /* A line too long to keep is read as far as it got (a long roster loses its last locos).
                   The end mark stops numbers running on into what's left of a longer line before. */
                line[line_length] = 0;
                read_line(line, line_length);
            }
            line_length = 0;
        } else if (line_length < LINE_MAX) {
            line[line_length++] = c;
        }
    }
}

/* --- sending commands --- */

void wt_hello(const unsigned char mac[6])
{
    /* Built here, where text is ASCII: the program's own strings are PETSCII. */
    static const char hex[] = "0123456789ABCDEF";
    unsigned char i;
    send_text("NC64 Ultimate");
    out[0] = 'H';
    out[1] = 'U';
    for (i = 0; i < 6; ++i) {
        out[2 + i * 2] = hex[mac[i] >> 4];
        out[3 + i * 2] = hex[mac[i] & 15];
    }
    finish(14);
    send_text("*+");    /* heartbeats on: if the C64 goes quiet, its loco is stopped */
}

void wt_heartbeat(void)
{
    send_text("*");
}

void wt_release(void)
{
    if (wt_have_loco) {
        send_text("M0-*<;>r");
        wt_have_loco = 0;
        wt_changed |= WT_LOCO;
    }
}

void wt_acquire(unsigned int address, unsigned char is_long, const char *name)
{
    unsigned char length, k;
    wt_release();
    wt_address = address;
    wt_long = is_long;
    make_key();
    if (name) {
        copy_text(wt_loco_name, name, strlen(name), WT_NAME);
    } else {
        memcpy(wt_loco_name, "Loco ", 5);
        wt_loco_name[5 + put_number(wt_loco_name + 5, address)] = 0;
    }
    wt_speed = 0;
    wt_emergency = 0;
    wt_forward = 1;
    wt_functions = 0;
    memset(wt_labels, 0, sizeof(wt_labels));
    wt_have_loco = 1;
    wt_hold = 0;
    /* M0+L144<;>L144 */
    out[0] = 'M';
    out[1] = '0';
    out[2] = '+';
    length = 3;
    for (k = 0; key[k]; ++k) {
        out[length++] = key[k];
    }
    memcpy(out + length, PART, 3);
    length += 3;
    for (k = 0; key[k]; ++k) {
        out[length++] = key[k];
    }
    finish(length);
    wt_changed |= WT_LOCO | WT_SPEED | WT_DIR | WT_FUNCS;
}

void wt_set_speed(unsigned char speed)
{
    unsigned char length;
    if (!wt_have_loco) {
        return;
    }
    wt_speed = speed > 126 ? 126 : speed;
    wt_emergency = 0;
    length = start_action();
    out[length++] = 'V';
    length += put_number(out + length, wt_speed);
    finish(length);
    wt_changed |= WT_SPEED;
}

void wt_set_direction(unsigned char forward)
{
    unsigned char length;
    if (!wt_have_loco) {
        return;
    }
    wt_forward = forward ? 1 : 0;
    length = start_action();
    out[length++] = 'R';
    out[length++] = wt_forward ? '1' : '0';
    finish(length);
    wt_changed |= WT_DIR;
}

void wt_emergency_stop(void)
{
    unsigned char length;
    if (!wt_have_loco) {
        return;
    }
    wt_speed = 0;
    wt_emergency = 1;
    length = start_action();
    out[length++] = 'X';
    finish(length);
    wt_changed |= WT_SPEED;
}

void wt_press_function(unsigned char number)
{
    /* Key down then key up: Simple-Train toggles a latching function
       (lights) and gives a momentary one (horn) a short blip. */
    unsigned char length, down;
    if (!wt_have_loco || number > 28) {
        return;
    }
    for (down = 1; down != 0xFF; --down) {
        length = start_action();
        out[length++] = 'F';
        out[length++] = down ? '1' : '0';
        length += put_number(out + length, number);
        finish(length);
    }
}

void wt_toggle_point(unsigned char index)
{
    unsigned char length;
    if (index >= wt_point_count) {
        return;
    }
    memcpy(out, "PTA2", 4);
    length = strlen(wt_points[index].system);
    memcpy(out + 4, wt_points[index].system, length);
    finish(length + 4);
}
