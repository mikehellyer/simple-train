/* Runs the C64's WiThrottle code on the PC: make -C c64 test */
#include <stdio.h>
#include <string.h>
#include "../src/wt.h"

static char sent[4096];
static int failures;

static void capture(const char *line, unsigned int length)
{
    strncat(sent, line, length);
}

#define CHECK(condition) do { if (!(condition)) { printf("FAIL line %d: %s\n", __LINE__, #condition); ++failures; } } while (0)

static void feed(const char *text)
{
    wt_feed(text, strlen(text));
}

int main(void)
{
    wt_send = capture;
    wt_reset();

    /* What Simple-Train says when the C64 connects. */
    feed("VN2.0\nRL2]\\[Class 08 Shunter}|{144}|{L]\\[Pug}|{3}|{S\nPPA2\n");
    feed("PTT]\\[Points}|{Point]\\[Closed}|{2]\\[Thrown}|{4\n");
    feed("PTL]\\[NT1}|{Loop west}|{2]\\[NT3}|{Siding}|{1\r\nRCC0\nHTSimple-Train\n*10\n");
    CHECK(wt_roster_count == 2);
    CHECK(strcmp(wt_roster[0].name, "Class 08 Shunter") == 0);
    CHECK(wt_roster[0].address == 144 && wt_roster[0].is_long == 1);
    CHECK(wt_roster[1].address == 3 && wt_roster[1].is_long == 0);
    CHECK(wt_point_count == 2);
    CHECK(strcmp(wt_points[1].system, "NT3") == 0 && strcmp(wt_points[1].name, "Siding") == 0);
    CHECK(wt_points[0].state == 2 && wt_points[1].state == 1);

    {
        static const unsigned char mac[6] = { 0x00, 0x11, 0x22, 0x33, 0x44, 0xAB };
        wt_hello(mac);
    }
    CHECK(strcmp(sent, "NC64 Ultimate\nHU0011223344AB\n*+\n") == 0);

    sent[0] = 0;
    wt_acquire(144, 1, "Class 08 Shunter");
    CHECK(strcmp(sent, "M0+L144<;>L144\n") == 0);
    feed("M0+L144<;>\nM0LL144<;>]\\[Lights]\\[Sound]\\[Horn]\\[]\\[]\\[\nM0AL144<;>F10\nM0AL144<;>V20\nM0AL144<;>R0\n");
    CHECK(strcmp(wt_labels[0], "Lights") == 0 && strcmp(wt_labels[2], "Horn") == 0 && wt_labels[3][0] == 0);
    CHECK(wt_functions == 1 && wt_speed == 20 && wt_forward == 0);

    /* Changes for another loco are not ours. */
    feed("M0AS3<;>V99\nM1AL144<;>V99\n");
    CHECK(wt_speed == 20);

    /* A short line after a longer one: no digits carried over. */
    feed("M0AL144<;>F028\nM0AL144<;>V5\n");
    CHECK(wt_speed == 5);

    sent[0] = 0;
    wt_set_speed(126);
    wt_set_direction(1);
    wt_press_function(2);
    wt_emergency_stop();
    CHECK(strcmp(sent, "M0AL144<;>V126\nM0AL144<;>R1\nM0AL144<;>F12\nM0AL144<;>F02\nM0AL144<;>X\n") == 0);
    CHECK(wt_speed == 0 && wt_emergency == 1);

    /* Echoes of our own changes are ignored while wt_hold is set. */
    wt_hold = 5;
    feed("M0AL144<;>V40\n");
    CHECK(wt_speed == 0);
    wt_hold = 0;
    feed("M0AL144<;>V-1\n");
    CHECK(wt_emergency == 1);

    sent[0] = 0;
    wt_toggle_point(1);
    CHECK(strcmp(sent, "PTA2NT3\n") == 0);
    feed("PTA4NT3\n");
    CHECK(wt_points[1].state == 4);

    feed("HMThe programming track is in use\n");
    CHECK(strcmp(wt_alert, "The programming track is in use") == 0);

    sent[0] = 0;
    wt_release();
    CHECK(strcmp(sent, "M0-*<;>r\n") == 0 && wt_have_loco == 0);

    /* A line split across two reads. */
    feed("RL1]\\[Fly");
    feed("ing Scotsman}|{4472}|{L\n");
    CHECK(wt_roster_count == 1 && strcmp(wt_roster[0].name, "Flying Scotsman") == 0 && wt_roster[0].address == 4472);

    sent[0] = 0;
    wt_acquire(3, 0, 0);
    CHECK(strcmp(wt_loco_name, "Loco 3") == 0 && strcmp(sent, "M0+S3<;>S3\n") == 0);

    if (failures) {
        printf("%d failed\n", failures);
        return 1;
    }
    printf("all passed\n");
    return 0;
}
