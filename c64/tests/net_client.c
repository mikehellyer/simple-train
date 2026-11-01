/* The C64 throttle's protocol code, run on the PC against a real
   Simple-Train (tests/test_c64_client.py starts one). Usage:
   net_client PORT   — prints what it saw, exits 0 on success. */
#include <arpa/inet.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include "../src/wt.h"

static int sock;

static void send_line(const char *line, unsigned int length)
{
    if (write(sock, line, length) < 0) {
        perror("write");
    }
}

/* Read for up to `ms`, or until `until` (if given) becomes true. */
static void pump(int ms, int (*until)(void))
{
    char buffer[512];
    struct pollfd fd = { sock, POLLIN, 0 };
    while (ms > 0) {
        if (until && until()) {
            return;
        }
        if (poll(&fd, 1, 20) > 0) {
            ssize_t got = read(sock, buffer, sizeof(buffer));
            if (got <= 0) {
                return;
            }
            wt_feed(buffer, (unsigned int)got);
        }
        ms -= 20;
    }
}

static int have_roster(void) { return wt_roster_count > 0 && wt_point_count > 0; }
static int have_labels(void) { return wt_labels[0][0] != 0; }
static int speed_is_33(void) { return wt_speed == 33; }

int main(int argc, char **argv)
{
    static const unsigned char mac[6] = { 0xC6, 0x40, 0, 0, 0, 1 };
    struct sockaddr_in where;
    int failures = 0;
    if (argc < 2) {
        return 2;
    }
    sock = socket(AF_INET, SOCK_STREAM, 0);
    memset(&where, 0, sizeof(where));
    where.sin_family = AF_INET;
    where.sin_port = htons((unsigned short)atoi(argv[1]));
    where.sin_addr.s_addr = htonl(0x7F000001);
    if (connect(sock, (struct sockaddr *)&where, sizeof(where)) < 0) {
        perror("connect");
        return 1;
    }
    wt_reset();
    wt_send = send_line;
    wt_hello(mac);
    pump(3000, have_roster);
    printf("roster %u: %s %u%s; points %u: %s\n", wt_roster_count, wt_roster[0].name,
           wt_roster[0].address, wt_roster[0].is_long ? "L" : "S", wt_point_count, wt_points[0].name);
    if (!have_roster()) failures++;

    wt_acquire(wt_roster[0].address, wt_roster[0].is_long, wt_roster[0].name);
    pump(3000, have_labels);
    printf("labels: %s %s %s\n", wt_labels[0], wt_labels[1], wt_labels[2]);
    if (!have_labels()) failures++;

    wt_set_speed(50);
    wt_set_direction(0);
    wt_press_function(0);
    wt_toggle_point(0);
    pump(800, 0);
    printf("after driving: speed %u forward %u F0 %lu point %u\n", wt_speed, wt_forward,
           wt_functions & 1, wt_points[0].state);
    if (wt_speed != 50 || wt_forward != 0 || !(wt_functions & 1) || wt_points[0].state != 4) failures++;

    /* The Python side now sets the speed to 33 from the app's own throttle. */
    printf("READY\n");
    fflush(stdout);
    pump(5000, speed_is_33);
    printf("speed from the app: %u\n", wt_speed);
    if (wt_speed != 33) failures++;

    wt_release();
    pump(300, 0);
    close(sock);
    printf(failures ? "FAILED\n" : "OK\n");
    return failures ? 1 : 0;
}
