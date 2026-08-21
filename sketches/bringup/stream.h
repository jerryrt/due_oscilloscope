#ifndef STREAM_H
#define STREAM_H
#include <stdint.h>
#include <stddef.h>

void stream_start(uint32_t trigger_hz);
void stream_stop(void);
bool stream_active(void);
void stream_service(void);
void stream_report(char *buf, size_t n);

#endif /* STREAM_H */
