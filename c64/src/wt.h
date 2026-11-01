/* The C64's side of the WiThrottle protocol: what Simple-Train sends
   (roster, points, loco changes, messages) is read into the tables below,
   and the wt_ functions build the commands to send. Everything here is
   plain ASCII and plain C, so it is tested on the PC too (c64/tests). */
#ifndef WT_H
#define WT_H

#define WT_MAX_ROSTER 40
#define WT_MAX_POINTS 40
#define WT_NAME 17       /* 16 characters and the end */
#define WT_LABELS 13     /* F0-F12 have names on screen */
#define WT_LABEL 9

struct wt_roster_entry {
    char name[WT_NAME];
    unsigned int address;
    unsigned char is_long;
};

struct wt_point {
    char system[8];      /* e.g. "NT12" */
    char name[WT_NAME];
    unsigned char state; /* 1 not known, 2 closed, 4 thrown */
};

/* What has changed since the screen last looked (wt_changed bits). */
#define WT_ROSTER  0x01
#define WT_POINTS  0x02
#define WT_SPEED   0x04
#define WT_DIR     0x08
#define WT_FUNCS   0x10
#define WT_ALERT   0x20
#define WT_LOCO    0x40

extern struct wt_roster_entry wt_roster[WT_MAX_ROSTER];
extern unsigned char wt_roster_count;
extern struct wt_point wt_points[WT_MAX_POINTS];
extern unsigned char wt_point_count;

extern unsigned char wt_have_loco;
extern unsigned int wt_address;
extern unsigned char wt_long;
extern char wt_loco_name[WT_NAME];
extern unsigned char wt_speed;        /* 0-126 */
extern unsigned char wt_emergency;    /* stopped with an emergency stop */
extern unsigned char wt_forward;
extern unsigned long wt_functions;    /* bit n = Fn on (F0-F28) */
extern char wt_labels[WT_LABELS][WT_LABEL];
extern char wt_alert[41];
extern unsigned char wt_changed;
extern unsigned char wt_hold;         /* frames to ignore echoes of our own speed/direction */

/* Where the commands go: set by the program to write to the socket. */
extern void (*wt_send)(const char *line, unsigned int length);

void wt_reset(void);
void wt_feed(const char *bytes, unsigned int length);
void wt_hello(const unsigned char mac[6]);   /* names us "C64 Ultimate", id from the MAC */
void wt_heartbeat(void);
void wt_acquire(unsigned int address, unsigned char is_long, const char *name);  /* name 0: "Loco 144" */
void wt_release(void);
void wt_set_speed(unsigned char speed);
void wt_set_direction(unsigned char forward);
void wt_emergency_stop(void);
void wt_press_function(unsigned char number);
void wt_toggle_point(unsigned char index);

#endif
