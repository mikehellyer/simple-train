/* Simple-Train C64 throttle, for the Commodore 64 Ultimate.

   Connects to Simple-Train on the PC through the Ultimate's network (its
   Command Interface), the same way Engine Driver on a phone does, then:
     - pick a loco from the Simple-Train roster (or type an address)
     - drive it: joystick in port 2 or the keyboard
     - switch points from the track plan

   Text from the network is ASCII; this file's own strings are PETSCII
   (cc65 converts them), so network text goes through show() to be printed. */
#include <c64.h>
#include <cbm.h>
#include <conio.h>
#include <string.h>
#include <stdlib.h>
#include "uci.h"
#include "wt.h"

#ifndef SERVER_IP
#define SERVER_IP "192.168.1.201"
#endif
#define SERVER_PORT 12090
#define HEARTBEAT_FRAMES 200   /* about every 4 seconds */
#define HOLD_FRAMES 25         /* ignore echoes of our own speed changes this long */
#define LIST_ROWS 18
#define BAR 30

#define JOY (*(volatile unsigned char *)0xDC00)
#define JOY_UP 0x01
#define JOY_DOWN 0x02
#define JOY_LEFT 0x04
#define JOY_RIGHT 0x08
#define JOY_FIRE 0x10

enum { CONNECT, LOCOS, DRIVE, POINTS };

static unsigned char screen = CONNECT;
static int sock = -1;
static char server[16] = SERVER_IP;
static char netbuf[256];
static unsigned char selected, first_row;
static unsigned int heartbeat;
static unsigned char wanted_speed, sent_speed;
static unsigned char joy_before;
static unsigned char joy_repeat;
static char message[41];

/* --- the screen --- */

static void wait_frame(void)
{
    while (VIC.rasterline < 250) {
    }
    while (VIC.rasterline >= 250) {
    }
}

static char petscii(char c)
{
    if (c >= 0x41 && c <= 0x5A) {
        return c | 0x80;          /* ASCII capitals -> PETSCII capitals */
    }
    if (c >= 0x61 && c <= 0x7A) {
        return c - 0x20;          /* ASCII small -> PETSCII small */
    }
    if (c < 0x20 || c > 0x7E || c == 0x5C || c == 0x5E || c == 0x5F || c == 0x60 ||
        (c >= 0x7B && c <= 0x7E)) {
        return '-';
    }
    return c;                     /* digits, space and most punctuation are the same */
}

static void show(const char *ascii, unsigned char width)
{
    unsigned char i = 0;
    while (ascii[i] && i < width) {
        cputc(petscii(ascii[i]));
        ++i;
    }
    while (i++ < width) {
        cputc(' ');
    }
}

static void show_number(unsigned int value, unsigned char width, unsigned char zeros)
{
    char text[7];
    unsigned char length;
    utoa(value, text, 10);
    length = strlen(text);
    while (length < width) {
        cputc(zeros ? '0' : ' ');
        ++length;
    }
    cputs(text);
}

static void show_address(unsigned int address, unsigned char is_long)
{
    /* NCE style: long addresses have four digits (0144). */
    show_number(address, is_long ? 4 : 0, 1);
}

static void title(const char *what)
{
    gotoxy(0, 0);
    revers(1);
    textcolor(COLOR_YELLOW);
    cputs(" simple-train  ");
    textcolor(COLOR_WHITE);
    cputs(what);
    cclear(25 - strlen(what));
    revers(0);
}

static void say(const char *petscii_text)
{
    strncpy(message, petscii_text, 40);
    message[40] = 0;
    gotoxy(0, 24);
    textcolor(COLOR_YELLOW);
    cputs(message);
    cclear(40 - strlen(message));
    textcolor(COLOR_GRAY3);
}

static void show_alert(void)
{
    gotoxy(0, 24);
    textcolor(COLOR_YELLOW);
    show(wt_alert, 39);
    textcolor(COLOR_GRAY3);
}

/* --- the network --- */

static void send_line(const char *line, unsigned int length)
{
    if (sock >= 0) {
        sock_write((unsigned char)sock, line, length);
    }
}

static void disconnect(const char *why)
{
    if (sock >= 0) {
        wt_release();
        sock_close((unsigned char)sock);
    }
    sock = -1;
    screen = CONNECT;
    strncpy(message, why, 40);
}

/* Read whatever has arrived; false if the connection has gone. */
static unsigned char poll_network(void)
{
    int got;
    unsigned char reads = 0;
    if (sock < 0) {
        return 0;
    }
    do {
        got = sock_read((unsigned char)sock, netbuf, sizeof(netbuf));
        if (got == 0) {
            disconnect("simple-train closed the connection");
            return 0;
        }
        if (got > 0) {
            wt_feed(netbuf, (unsigned int)got);
        }
    } while (got > 0 && ++reads < 8);
    if (++heartbeat >= HEARTBEAT_FRAMES) {
        heartbeat = 0;
        wt_heartbeat();
    }
    if (wt_hold) {
        --wt_hold;
    }
    return 1;
}

/* --- connecting --- */

static void draw_connect(void)
{
    unsigned char ip[4], i;
    clrscr();
    title("c64 throttle");
    textcolor(COLOR_GRAY3);
    gotoxy(0, 3);
    cputs("command interface: ");
    if (!uci_present()) {
        textcolor(COLOR_LIGHTRED);
        cputs("not found");
        textcolor(COLOR_GRAY3);
        cputsxy(0, 5, "switch it on in the ultimate menu:");
        cputsxy(0, 6, "c64 and cartridge settings ->");
        cputsxy(0, 7, "command interface -> enabled");
        return;
    }
    textcolor(COLOR_LIGHTGREEN);
    cputs("ok");
    textcolor(COLOR_GRAY3);
    gotoxy(0, 4);
    cputs("this c64:          ");
    if (net_ip(ip)) {
        for (i = 0; i < 4; ++i) {
            show_number(ip[i], 0, 0);
            if (i < 3) {
                cputc('.');
            }
        }
    } else {
        textcolor(COLOR_LIGHTRED);
        cputs("no network address");
        textcolor(COLOR_GRAY3);
    }
    cputsxy(0, 7, "simple-train pc address:");
    cputsxy(0, 10, "on the pc, tick 'let phones drive'");
    cputsxy(0, 11, "on the throttles tab: it shows the");
    cputsxy(0, 12, "address to type here.");
    cputsxy(0, 14, "return: connect   del: rub out");
    if (message[0]) {
        say(message);
    }
}

static void edit_address(void)
{
    unsigned char length = strlen(server);
    unsigned char key;
    gotoxy(0, 8);
    textcolor(COLOR_WHITE);
    cputs(server);
    cclear(16 - length);
    gotoxy(length, 8);
    cursor(1);
    for (;;) {
        key = cgetc();
        if (key == CH_ENTER && length) {
            break;
        }
        if (key == CH_DEL && length) {
            server[--length] = 0;
            cputcxy(length, 8, ' ');
            gotoxy(length, 8);
        } else if (((key >= '0' && key <= '9') || key == '.') && length < 15) {
            server[length++] = key;
            server[length] = 0;
            cputc(key);
        }
    }
    cursor(0);
    textcolor(COLOR_GRAY3);
}

static void try_connect(void)
{
    unsigned char mac[6] = { 0, 0, 0, 0, 0, 0 };
    say("connecting...");
    net_mac(mac);
    sock = tcp_open(server, SERVER_PORT);   /* digits and dots: the same in ascii */
    if (sock < 0) {
        say("couldn't connect. is simple-train running");
        gotoxy(0, 23);
        cputs("with 'let phones drive' ticked?");
        message[0] = 0;
        return;
    }
    wt_reset();
    wt_send = send_line;
    wt_hello(mac);
    heartbeat = 0;
    message[0] = 0;
    selected = first_row = 0;
    screen = LOCOS;
}

/* --- choosing a loco --- */

static void draw_locos(void)
{
    unsigned char row, index;
    clrscr();
    title("choose a loco");
    textcolor(COLOR_GRAY3);
    if (!wt_roster_count) {
        cputsxy(0, 3, "no locos in the roster yet.");
        cputsxy(0, 4, "add them on simple-train's locos tab,");
        cputsxy(0, 5, "or press a to type an address.");
    }
    for (row = 0; row < LIST_ROWS; ++row) {
        index = first_row + row;
        if (index >= wt_roster_count) {
            break;
        }
        gotoxy(1, 2 + row);
        revers(index == selected);
        textcolor(index == selected ? COLOR_WHITE : COLOR_GRAY3);
        show(wt_roster[index].name, 30);
        cputc(' ');
        show_address(wt_roster[index].address, wt_roster[index].is_long);
        cclear(5);
        revers(0);
    }
    textcolor(COLOR_GRAY2);
    cputsxy(0, 21, "up/down choose  return drive");
    cputsxy(0, 22, "a type an address  p points");
    cputsxy(0, 23, wt_have_loco ? "<- back to the throttle" : "q disconnect");
    textcolor(COLOR_GRAY3);
}

static void type_address(void)
{
    char text[6];
    unsigned char length = 0;
    unsigned int address;
    unsigned char key;
    say("address (1-10239), return: ");
    gotoxy(29, 24);
    cursor(1);
    for (;;) {
        key = cgetc();
        if (key == CH_ENTER) {
            break;
        }
        if (key == CH_STOP || key == CH_ESC) {
            length = 0;
            break;
        }
        if (key == CH_DEL && length) {
            --length;
            gotoxy(29 + length, 24);
            cputc(' ');
            gotoxy(29 + length, 24);
        } else if (key >= '0' && key <= '9' && length < 5) {
            text[length++] = key;
            cputc(key);
        }
    }
    cursor(0);
    text[length] = 0;
    address = length ? (unsigned int)atoi(text) : 0;
    if (address >= 1 && address <= 10239) {
        /* NCE: 1-127 short, above that long */
        wt_acquire(address, address > 127, 0);
        wanted_speed = sent_speed = 0;
        screen = DRIVE;
    } else {
        say("");
    }
}

/* --- driving --- */

static const char *const help[] = {
    "joy/crsr up-down: speed  + - by ten",
    "joy/crsr left-right: direction",
    "fire/space: stop   run-stop/e: emergency",
    "0-9: f0-f9   f1 f3 f5 keys: f10-f12",
    "l: locos   p: points   q: disconnect",
};

static void draw_speed(void)
{
    unsigned char filled = (unsigned char)((wt_speed * BAR + 63) / 126), i;
    gotoxy(0, 6);
    textcolor(COLOR_GRAY3);
    cputs("speed ");
    gotoxy(0, 7);
    textcolor(wt_emergency ? COLOR_LIGHTRED : COLOR_LIGHTGREEN);
    revers(1);
    for (i = 0; i < filled; ++i) {
        cputc(' ');
    }
    revers(0);
    textcolor(COLOR_GRAY1);
    for (; i < BAR; ++i) {
        cputc(0xA4);   /* a thin line */
    }
    textcolor(COLOR_WHITE);
    gotoxy(BAR + 2, 7);
    if (wt_emergency) {
        textcolor(COLOR_LIGHTRED);
        cputs("stop!");
    } else {
        show_number((wt_speed * 100u + 63) / 126, 3, 0);
        cputs("% ");
    }
    textcolor(COLOR_GRAY2);
    gotoxy(6, 6);
    cputs("step ");
    show_number(wt_speed, 3, 0);
    cputs(" of 126");
    textcolor(COLOR_GRAY3);
}

static void draw_direction(void)
{
    gotoxy(0, 9);
    revers(!wt_forward);
    textcolor(!wt_forward ? COLOR_LIGHTGREEN : COLOR_GRAY2);
    cputs(" << reverse ");
    revers(0);
    cputs("    ");
    revers(wt_forward);
    textcolor(wt_forward ? COLOR_LIGHTGREEN : COLOR_GRAY2);
    cputs(" forward >> ");
    revers(0);
    textcolor(COLOR_GRAY3);
}

static void draw_functions(void)
{
    unsigned char number, x, y;
    for (number = 0; number < WT_LABELS; ++number) {
        x = number < 7 ? 0 : 20;
        y = 11 + (number < 7 ? number : number - 7);
        gotoxy(x, y);
        if (wt_functions & (1UL << number)) {
            revers(1);
            textcolor(COLOR_YELLOW);
        } else {
            textcolor(COLOR_GRAY3);
        }
        cputc('f');
        show_number(number, 2, 0);
        cputc(' ');
        if (wt_labels[number][0]) {
            show(wt_labels[number], 15);
        } else {
            cclear(15);
        }
        revers(0);
    }
    textcolor(COLOR_GRAY3);
}

static void draw_drive(void)
{
    unsigned char i;
    clrscr();
    title("throttle");
    textcolor(COLOR_WHITE);
    gotoxy(0, 2);
    show(wt_loco_name, 30);
    textcolor(COLOR_GRAY3);
    gotoxy(0, 3);
    cputs("address ");
    show_address(wt_address, wt_long);
    draw_speed();
    draw_direction();
    draw_functions();
    textcolor(COLOR_GRAY2);
    for (i = 0; i < 5; ++i) {
        cputsxy(0, 19 + i, help[i]);
    }
    textcolor(COLOR_GRAY3);
}

static void change_speed(int by)
{
    int speed = (int)wanted_speed + by;
    wanted_speed = speed < 0 ? 0 : (speed > 126 ? 126 : (unsigned char)speed);
    wt_speed = wanted_speed;
    wt_emergency = 0;
    wt_hold = HOLD_FRAMES;
    draw_speed();
}

static void set_direction(unsigned char forward)
{
    if (forward != wt_forward) {
        wt_hold = HOLD_FRAMES;
        wt_set_direction(forward);
        draw_direction();
    }
}

static void stop(void)
{
    wanted_speed = 0;
    sent_speed = 0;
    wt_hold = HOLD_FRAMES;
    wt_set_speed(0);
    draw_speed();
}

static void emergency(void)
{
    wanted_speed = sent_speed = 0;
    wt_hold = HOLD_FRAMES;
    wt_emergency_stop();
    draw_speed();
}

static void drive_joystick(void)
{
    unsigned char joy = ~JOY & 0x1F;
    unsigned char pressed = joy & ~joy_before;
    if (joy & (JOY_UP | JOY_DOWN)) {
        /* held: one step every other frame, faster after a moment */
        if (!(joy_before & (JOY_UP | JOY_DOWN)) || ++joy_repeat >= 2) {
            joy_repeat = 0;
            change_speed((joy & JOY_UP) ? 1 : -1);
        }
    }
    if (pressed & JOY_LEFT) {
        set_direction(0);
    }
    if (pressed & JOY_RIGHT) {
        set_direction(1);
    }
    if (pressed & JOY_FIRE) {
        stop();
    }
    joy_before = joy;
}

static void drive_key(unsigned char key)
{
    switch (key) {
    case CH_CURS_UP: change_speed(2); break;
    case CH_CURS_DOWN: change_speed(-2); break;
    case '+': change_speed(10); break;
    case '-': change_speed(-10); break;
    case CH_CURS_LEFT: set_direction(0); break;
    case CH_CURS_RIGHT: set_direction(1); break;
    case ' ': stop(); break;
    case CH_STOP:
    case 'e': emergency(); break;
    case CH_F1: wt_press_function(10); break;
    case CH_F3: wt_press_function(11); break;
    case CH_F5: wt_press_function(12); break;
    case 'l': selected = first_row = 0; screen = LOCOS; break;
    case 'p': selected = first_row = 0; screen = POINTS; break;
    case 'q': stop(); disconnect("disconnected"); break;
    default:
        if (key >= '0' && key <= '9') {
            wt_press_function(key - '0');
        }
    }
}

/* --- points --- */

static void draw_points(void)
{
    unsigned char row, index, state;
    clrscr();
    title("points");
    textcolor(COLOR_GRAY3);
    if (!wt_point_count) {
        cputsxy(0, 3, "no points with an address on the");
        cputsxy(0, 4, "track plan yet.");
    }
    for (row = 0; row < LIST_ROWS; ++row) {
        index = first_row + row;
        if (index >= wt_point_count) {
            break;
        }
        state = wt_points[index].state;
        gotoxy(1, 2 + row);
        revers(index == selected);
        textcolor(index == selected ? COLOR_WHITE : COLOR_GRAY3);
        show(wt_points[index].name, 26);
        cputc(' ');
        textcolor(state == 4 ? COLOR_ORANGE : (state == 2 ? COLOR_LIGHTGREEN : COLOR_GRAY2));
        cputs(state == 4 ? "thrown " : (state == 2 ? "closed " : "   ?   "));
        revers(0);
    }
    textcolor(COLOR_GRAY2);
    cputsxy(0, 21, "up/down choose  return/fire switch it");
    cputsxy(0, 22, wt_have_loco ? "<- back to the throttle" : "<- back to the locos");
    textcolor(COLOR_GRAY3);
}

/* Moves the highlight in a list; true if it moved. */
static unsigned char list_move(unsigned char key, unsigned char count)
{
    if ((key == CH_CURS_DOWN) && selected + 1 < count) {
        ++selected;
    } else if (key == CH_CURS_UP && selected) {
        --selected;
    } else {
        return 0;
    }
    if (selected < first_row) {
        first_row = selected;
    } else if (selected >= first_row + LIST_ROWS) {
        first_row = selected - LIST_ROWS + 1;
    }
    return 1;
}

static unsigned char joystick_as_key(void)
{
    /* In the lists the joystick moves the highlight and fire chooses. */
    static unsigned char wait;
    unsigned char joy = ~JOY & 0x1F;
    if (!joy) {
        wait = 0;
        joy_before = 0;
        return 0;
    }
    if (joy == joy_before && wait && --wait) {
        return 0;
    }
    wait = joy == joy_before ? 6 : 15;
    joy_before = joy;
    if (joy & JOY_UP) return CH_CURS_UP;
    if (joy & JOY_DOWN) return CH_CURS_DOWN;
    if (joy & JOY_FIRE) return CH_ENTER;
    return 0;
}

/* --- the main loop --- */

int main(void)
{
    unsigned char key;
    unsigned char drawn = 0xFF;

    *(unsigned char *)0xD018 = 0x17;   /* the upper/lower case character set */
    *(unsigned char *)0x0291 = 0x80;   /* and keep it: no shift+commodore switching */
    bordercolor(COLOR_BLACK);
    bgcolor(COLOR_BLACK);
    textcolor(COLOR_GRAY3);

    for (;;) {
        if (screen == CONNECT) {
            draw_connect();
            drawn = CONNECT;
            if (!uci_present()) {
                cgetc();
                continue;
            }
            edit_address();
            try_connect();
            continue;
        }

        wait_frame();
        if (!poll_network()) {
            continue;
        }

        if (drawn != screen) {
            drawn = screen;
            wt_changed = 0;
            if (screen == LOCOS) draw_locos();
            else if (screen == DRIVE) draw_drive();
            else draw_points();
        }

        if (wt_changed) {
            unsigned char changed = wt_changed;
            wt_changed = 0;
            if (screen == LOCOS && (changed & WT_ROSTER)) draw_locos();
            if (screen == POINTS && (changed & WT_POINTS)) draw_points();
            if (screen == DRIVE) {
                if (changed & WT_LOCO) {
                    if (!wt_have_loco) {
                        screen = LOCOS;   /* the PC took the loco away */
                        continue;
                    }
                    draw_drive();
                }
                if (changed & WT_SPEED) {
                    wanted_speed = sent_speed = wt_speed;
                    draw_speed();
                }
                if (changed & WT_DIR) draw_direction();
                if (changed & WT_FUNCS) draw_functions();
            }
            if (changed & WT_ALERT) show_alert();
        }

        key = kbhit() ? cgetc() : 0;

        if (screen == DRIVE) {
            drive_joystick();
            if (key) {
                drive_key(key);
            }
            /* Send the speed at most every few frames while it's changing. */
            if (wanted_speed != sent_speed && !(heartbeat & 3) && !wt_emergency) {
                sent_speed = wanted_speed;
                wt_set_speed(wanted_speed);
                wt_hold = HOLD_FRAMES;
            }
            continue;
        }

        if (!key) {
            key = joystick_as_key();
        }
        if (!key) {
            continue;
        }
        if (screen == LOCOS) {
            if (list_move(key, wt_roster_count)) {
                draw_locos();
            } else if (key == CH_ENTER && selected < wt_roster_count) {
                wt_acquire(wt_roster[selected].address, wt_roster[selected].is_long, wt_roster[selected].name);
                wanted_speed = sent_speed = 0;
                screen = DRIVE;
            } else if (key == 'a') {
                type_address();
                if (screen == LOCOS) draw_locos();
            } else if (key == 'p') {
                selected = first_row = 0;
                screen = POINTS;
            } else if (key == CH_LEFT_ARROW && wt_have_loco) {
                screen = DRIVE;
            } else if (key == 'q') {
                disconnect("disconnected");
            }
        } else if (screen == POINTS) {
            if (list_move(key, wt_point_count)) {
                draw_points();
            } else if (key == CH_ENTER && selected < wt_point_count) {
                wt_toggle_point(selected);
            } else if (key == CH_LEFT_ARROW || key == CH_DEL) {
                selected = first_row = 0;
                screen = wt_have_loco ? DRIVE : LOCOS;
            }
        }
    }
    return 0;
}
