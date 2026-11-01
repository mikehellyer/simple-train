/* See uci.h. The protocol: write the command bytes to $DF1D, set PUSH_CMD;
   wait while the Ultimate is busy; read the reply's data ($DF1E) and status
   ($DF1F) while their "available" bits are set; then set DATA_ACC to say
   the reply was taken. */
#include "ascii.h"
#include "uci.h"

#define CONTROL   (*(volatile unsigned char *)0xDF1C)  /* write */
#define STATUS    (*(volatile unsigned char *)0xDF1C)  /* read */
#define COMMAND   (*(volatile unsigned char *)0xDF1D)  /* write */
#define IDENT     (*(volatile unsigned char *)0xDF1D)  /* read: $C9 (or $49 with an IRQ pending) */
#define RESPONSE  (*(volatile unsigned char *)0xDF1E)
#define STATUSDAT (*(volatile unsigned char *)0xDF1F)

#define PUSH_CMD  0x01
#define DATA_ACC  0x02
#define ABORT     0x04
#define CLR_ERR   0x08

#define DATA_AV   0x80
#define STAT_AV   0x40
#define STATE     0x30
#define S_IDLE    0x00
#define S_BUSY    0x10
#define S_LAST    0x20
#define S_MORE    0x30
#define ERROR     0x08

#define NETWORK   0x03

unsigned char uci_data[UCI_DATA_MAX];
unsigned int uci_data_len;
char uci_status[64];

unsigned char uci_present(void)
{
    return (IDENT & 0x7F) == 0x49;
}

unsigned char uci_ok(void)
{
    return uci_status[0] == '0' && uci_status[1] == '0';
}

static void wait_idle(void)
{
    unsigned int tries = 0;
    if ((STATUS & STATE) != S_IDLE) {
        CONTROL = ABORT;
    }
    while ((STATUS & STATE) != S_IDLE && ++tries) {
        /* wait (at most 65535 polls) */
    }
    if (STATUS & ERROR) {
        CONTROL = CLR_ERR;
    }
}

void uci_command(const unsigned char *command, unsigned int length)
{
    unsigned int i;
    unsigned char state;
    unsigned int status_len = 0;
    unsigned long tries;

    uci_data_len = 0;
    uci_status[0] = 0;
    wait_idle();
    for (i = 0; i < length; ++i) {
        COMMAND = command[i];
    }
    CONTROL = PUSH_CMD;

    for (;;) {
        /* Busy until the reply is ready (opening a connection can take seconds). */
        tries = 0;
        while (((state = STATUS & STATE) == S_BUSY) && ++tries < 400000UL) {
        }
        if (state == S_BUSY) {
            CONTROL = ABORT;
            uci_status[0] = '9';
            uci_status[1] = '9';
            uci_status[2] = 0;
            return;
        }
        if (state == S_IDLE) {
            break;
        }
        while (STATUS & DATA_AV) {
            unsigned char byte = RESPONSE;
            if (uci_data_len < UCI_DATA_MAX) {
                uci_data[uci_data_len++] = byte;
            }
        }
        while (STATUS & STAT_AV) {
            unsigned char byte = STATUSDAT;
            if (status_len < sizeof(uci_status) - 1) {
                uci_status[status_len++] = byte;
            }
        }
        uci_status[status_len] = 0;
        CONTROL = DATA_ACC;
        if (state == S_LAST) {
            break;
        }
        /* S_MORE: another block follows. */
    }
    tries = 0;
    while ((STATUS & STATE) == S_LAST && ++tries < 10000UL) {
    }
}

unsigned char net_interfaces(void)
{
    static const unsigned char command[] = { NETWORK, 0x02 };
    uci_command(command, sizeof(command));
    return uci_data_len ? uci_data[0] : 0;
}

unsigned char net_ip(unsigned char ip[4])
{
    static const unsigned char command[] = { NETWORK, 0x05, 0 };
    unsigned char i;
    uci_command(command, sizeof(command));
    if (uci_data_len < 4) {
        return 0;
    }
    for (i = 0; i < 4; ++i) {
        ip[i] = uci_data[i];
    }
    return ip[0] != 0;
}

unsigned char net_mac(unsigned char mac[6])
{
    static const unsigned char command[] = { NETWORK, 0x04, 0 };
    unsigned char i;
    uci_command(command, sizeof(command));
    if (uci_data_len < 6) {
        return 0;
    }
    for (i = 0; i < 6; ++i) {
        mac[i] = uci_data[i];
    }
    return 1;
}

int tcp_open(const char *host, unsigned int port)
{
    static unsigned char command[4 + 64];
    unsigned char length = 4;
    command[0] = NETWORK;
    command[1] = 0x07;
    command[2] = port & 0xFF;
    command[3] = port >> 8;
    while (*host && length < sizeof(command) - 1) {
        command[length++] = *host++;
    }
    command[length++] = 0;
    uci_command(command, length);
    if (!uci_ok() || uci_data_len < 1) {
        return -1;
    }
    return uci_data[0];
}

int sock_write(unsigned char socket, const char *data, unsigned int length)
{
    static unsigned char command[3 + 256];
    unsigned int i;
    if (length > 256) {
        length = 256;
    }
    command[0] = NETWORK;
    command[1] = 0x11;
    command[2] = socket;
    for (i = 0; i < length; ++i) {
        command[3 + i] = data[i];
    }
    uci_command(command, 3 + length);
    if (!uci_ok()) {
        return -1;
    }
    return uci_data_len >= 2 ? (int)(uci_data[0] | (uci_data[1] << 8)) : (int)length;
}

int sock_read(unsigned char socket, char *into, unsigned int most)
{
    unsigned char command[5];
    unsigned int count, i;
    command[0] = NETWORK;
    command[1] = 0x10;
    command[2] = socket;
    command[3] = most & 0xFF;
    command[4] = most >> 8;
    uci_command(command, 5);
    if (uci_data_len < 2) {
        return uci_ok() ? SOCK_NONE : 0;
    }
    count = uci_data[0] | (uci_data[1] << 8);
    if (count == 0xFFFF) {
        return SOCK_NONE;    /* nothing yet */
    }
    if (count == 0) {
        return 0;            /* closed */
    }
    if (count > most) {
        count = most;
    }
    if (count > uci_data_len - 2) {
        count = uci_data_len - 2;
    }
    for (i = 0; i < count; ++i) {
        into[i] = uci_data[2 + i];
    }
    return (int)count;
}

void sock_close(unsigned char socket)
{
    unsigned char command[3];
    command[0] = NETWORK;
    command[1] = 0x09;
    command[2] = socket;
    uci_command(command, 3);
}
