/* A small driver for the Ultimate Command Interface (UCI) of the Commodore
   64 Ultimate and the other Ultimate products: just the network target,
   for one TCP connection. Written from the official register description
   (1541u-documentation: uci/core_uci_architecture and uci/network_target).

   The interface must be switched on in the Ultimate's menu:
   C64 and Cartridge Settings -> Command Interface -> Enabled. */
#ifndef UCI_H
#define UCI_H

#define UCI_DATA_MAX 900          /* the response queue holds 896 bytes */

extern unsigned char uci_data[UCI_DATA_MAX];
extern unsigned int uci_data_len;
extern char uci_status[64];       /* e.g. "00,OK" (ASCII) */

unsigned char uci_present(void);  /* 1 if the interface answers */
unsigned char uci_ok(void);       /* the last command's status was 00 */
void uci_command(const unsigned char *command, unsigned int length);

/* The network target. */
unsigned char net_interfaces(void);
unsigned char net_ip(unsigned char ip[4]);     /* 1 if it has one */
unsigned char net_mac(unsigned char mac[6]);
int tcp_open(const char *host, unsigned int port);   /* a socket, or -1 */
int sock_write(unsigned char socket, const char *data, unsigned int length);
int sock_read(unsigned char socket, char *into, unsigned int most);
    /* bytes read; SOCK_NONE if nothing has arrived yet; 0 if the other end closed */
void sock_close(unsigned char socket);

#define SOCK_NONE (-1)

#endif
