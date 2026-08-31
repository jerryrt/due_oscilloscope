/*
 * FreeRTOS configuration for Track C on the SAM3X8E.
 *
 * The choices here are the ones docs/rtos.md settled, plus the two the
 * owner ruled on in issue #45. Where this file departs from that note,
 * it says so.
 */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

/*
 * VECTOR ALIASING, and it is the whole of the SysTick question.
 *
 * bsp/startup_sam3x8e.c declares SVC_Handler and PendSV_Handler as
 * *weak* aliases of Default_Handler, so a strong definition elsewhere
 * wins. These three defines make port.c define functions literally
 * named SVC_Handler, PendSV_Handler and SysTick_Handler, which is that
 * strong definition. No change to the vector table is needed and none
 * is made - the table already names the right symbols.
 *
 * SysTick is the exception, and it is why Track C does not link
 * bsp/systick.c: that file defines SysTick_Handler *strongly*, and two
 * strong definitions are a duplicate-symbol error rather than an
 * override. docs/rtos.md states the rule - in the bare-metal build
 * SysTick belongs to the BSP, in the RTOS build it belongs to the
 * kernel - and this is where it bites. millis() and micros() come from
 * that file too, so anything Track C links must not need them until
 * the kernel provides an equivalent.
 */
#define vPortSVCHandler      SVC_Handler
#define xPortPendSVHandler   PendSV_Handler
#define xPortSysTickHandler  SysTick_Handler

/*
 * MCK is 78 MHz here and not the Due's usual 84 - CLAUDE.md, and every
 * RC in this project divides 39 MHz. Taken from the variable rather
 * than written as a literal so that this file cannot disagree with
 * bsp/clock.c: clock_set_mck() runs before the scheduler starts, so
 * SystemCoreClock is correct by the time FreeRTOS reads it.
 */
#ifndef __ASSEMBLER__
#include <stdint.h>
extern uint32_t SystemCoreClock;
#endif
#define configCPU_CLOCK_HZ            (SystemCoreClock)
#define configTICK_RATE_HZ            ((TickType_t)1000)

/*
 * NO HEAP. Issue #45 decision (4).
 *
 * docs/rtos.md proposed heap_4 with a sized configTOTAL_HEAP_SIZE.
 * Invariant 7 says "every buffer is fixed and known at build time... No
 * allocation", and although it governs "the working path" - so startup
 * allocation is arguably outside it - the invariant does not carve that
 * out. Static allocation satisfies it literally and needs no
 * interpretation to be blessed, and it removes a sizing question against
 * the same 96 KB the DMA buffers come out of. No MemMang file is
 * compiled at all, so a malloc cannot appear by accident.
 *
 * tests/test_no_heap.py is the mechanical guard, and it reads the
 * linked image rather than the sources.
 */
#define configSUPPORT_STATIC_ALLOCATION   1
#define configSUPPORT_DYNAMIC_ALLOCATION  0

#define configMAX_PRIORITIES          (5)
#define configMINIMAL_STACK_SIZE      ((uint16_t)128)
#define configMAX_TASK_NAME_LEN       (12)
#define configUSE_PREEMPTION          1
#define configUSE_IDLE_HOOK           0
/* The tick hook is Track C's millisecond counter - see
 * apps/rtos_bringup/time_rtos.c for why it is not
 * xTaskGetTickCount(). */
#define configUSE_TICK_HOOK           1
#define configUSE_16_BIT_TICKS        0
#define configIDLE_SHOULD_YIELD       1
#define configUSE_MUTEXES             1
#define configCHECK_FOR_STACK_OVERFLOW 2
#define configUSE_TIMERS              1
#define configTIMER_TASK_PRIORITY     (configMAX_PRIORITIES - 1)
#define configTIMER_QUEUE_LENGTH      8
#define configTIMER_TASK_STACK_DEPTH  (configMINIMAL_STACK_SIZE * 2)

/*
 * Cortex-M3 has 4 priority bits on this part, and ARM shifts them into
 * the top of the byte. So a "logical" priority of 5 is 5 << (8 - 4).
 *
 * The acquisition ISR sits ABOVE this ceiling and may call no FreeRTOS
 * API at all - it touches only the lock-free ring. docs/rtos.md is
 * explicit that this is the correct architecture bare-metal too and
 * that the RTOS merely makes it enforceable, which is why Track C is
 * tractable: it is not a rewrite of the data path.
 */
#define configPRIO_BITS                                4
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY        15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY   5
#define configKERNEL_INTERRUPT_PRIORITY \
    (configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    (configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))

#define INCLUDE_vTaskPrioritySet      1
#define INCLUDE_uxTaskPriorityGet     1
#define INCLUDE_vTaskDelete           0
#define INCLUDE_vTaskSuspend          1
#define INCLUDE_vTaskDelayUntil       1
#define INCLUDE_vTaskDelay            1
#define INCLUDE_xTaskGetSchedulerState 1

/* An assert that blinks is worth more than one that spins, because
 * there is no debug probe on this board - CLAUDE.md. led_blink_forever
 * needs no SysTick, which is what makes it safe from here. */
#ifndef __ASSEMBLER__
void rtos_assert_failed(const char *file, int line);
#define configASSERT(x) \
    do { if (!(x)) rtos_assert_failed(__FILE__, __LINE__); } while (0)
#endif

#endif /* FREERTOS_CONFIG_H */
