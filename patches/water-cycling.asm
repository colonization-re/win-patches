; water-cycling.asm -- the body patches/water-cycling.json writes over the first 123
; bytes of palette_cross_fade (1068:0d94), a function nothing in the game calls.
;
;   nasm -f bin -o water-cycling.bin patches/water-cycling.asm
;
; tools/patch_exe.py verify assembles this file and requires the result to equal the
; manifest's `new` bytes, so the source and the patch cannot drift apart.
;
; WHAT IT DOES. GameBrains_DoHuman's idle phase toggles the cursor blink every 25
; ticks (0.42 s) and calls MiniWin_HighlightActiveUnit from both of its branches. The
; two relocation records behind those far calls are re-pointed here, so each blink
; runs the tick first and then jumps on to MiniWin_HighlightActiveUnit with the
; caller's stack exactly as it was.
;
; THE TICK IS THE DOS ONE, ON THE ENTRIES THE WINDOWS ART RESERVED FOR IT. The DOS
; build rotates 8 palette entries (CYCLE.DAT: 0x78..0x7F) up by one from the timer
; interrupt, and only a few pixels use them: a line down the middle of each river
; (PHYS0.SS frames 1..31, one pixel of each entry in turn), the surf inside the beach
; pieces (150..153) and sparkles on the sea lane. The Windows water sheet, picture
; 0xcc, was drawn the same way. init_water_sprites installs it at palette 40 with 102
; colours, not 96: its raw 96..101 -- game entries 136..141 -- appear only on the river
; centres of sprites 0..31, the surf of 150..153 and the fish, and it cuts exactly those
; cells over sheet 201's plain rivers and beach (the table at SEG20:0x4526 is
; g_art_base[28]). Nothing ever rotated them. This does: palette_rotate(&g_game_palette,
; 136, 6, +1) -- up by one, as DOS does -- through the game's own dead palette_rotate
; (1068:06b5). Open sea, marsh, lakes and the fog-of-war edges keep their colours.
;
; It does nothing when "Water Color Cycling" is off in Game Options:
; GAMEFLAG_NO_WATER_CYCLING, 0x100 of SEG20:0x7784, which the Windows build stores and
; saves but never read until now.
;
; WHY THE BLIT. On a display without a palette (every Wine/otvdm setup, and most
; modern ones) AnimatePalette is skipped (palette_animate_range, mode 0), so the new
; colours reach the screen only through the WinG DIB colour table. GRPort_ColorSync
; re-sends that table on the next CopyToScreen whenever the palette's seed (+0x406)
; differs from what the port last sent, so the seed is bumped and the map view is
; blitted. The seed is incremented rather than re-rolled: seed_nonzero_random would
; draw from the C runtime's rand() every half second.
;
; THE THREE FAR OPERANDS. Each `0xffff` below is a fixup site, left as the chain
; terminator a non-additive NE relocation record expects. They are filled at load time
; by three records that used to fix up palette_cross_fade's own calls (SEG14 records
; #81, #82, #83, whose sites fell inside these 123 bytes); the manifest moves each one
; to its operand here and gives it its new target.

bits 16
org 0x0d94

palette_rotate  equ 0x06b5              ; 1068:06b5, dead until now: rotate + AnimatePalette
PALETTE         equ 0x01ac              ; g_game_palette, SEG20:0x1ac
SEED            equ PALETTE + 0x406     ; its seed, read by GRPort_ColorSync
FLAGS_HI        equ 0x7785              ; high byte of g_game_flags (SEG20:0x7784)
NO_CYCLING      equ 0x01                ; GAMEFLAG_NO_WATER_CYCLING >> 8
FIRST           equ 136                 ; picture 0xcc's raw 96, installed at 40
COUNT           equ 6                   ; raw 96..101
VIEW_X0         equ 0x4c44              ; DGROUP: the map view, in tiles
VIEW_Y0         equ 0x4c46
VIEW_W          equ 0x4c50
VIEW_H          equ 0x4c52

water_hook:                             ; far, entered as MiniWin_HighlightActiveUnit(rec, on)
    push ds                             ; keeps si, di, bp and ds, as Borland code expects
    mov ax,ss                           ; DGROUP, as every -WS function takes it
    mov ds,ax
    db 0xb8                             ; mov ax,SEG SEG20
fixup_seg20:
    dw 0xffff                           ;   SEG14 record #83
    mov es,ax
    test byte [es:FLAGS_HI],NO_CYCLING
    jnz tick_done

    push ax                             ; SEG20, for after the call
    push byte 1                         ; palette_rotate(&g_game_palette, FIRST, COUNT, +1)
    push byte COUNT
    push word FIRST
    push ax
    push word PALETTE
    push cs
    call palette_rotate
    add sp,10
    pop es

    inc word [es:SEED]                  ; any change makes ColorSync re-send the colours
    jnz seeded
    inc word [es:SEED]                  ; 0 would read as "never set"
seeded:
    push word [VIEW_H]                  ; map_blit_tiles(x0, y0, w, h)
    push word [VIEW_W]
    push word [VIEW_Y0]
    push word [VIEW_X0]
    db 0x9a                             ; call far map_blit_tiles (1040:07f1)
fixup_blit:
    dw 0xffff, 0x0000                   ;   SEG14 record #81
    add sp,8
tick_done:
    pop ds
    db 0xea                             ; jmp far MiniWin_HighlightActiveUnit (1060:0fdb),
fixup_miniwin:                          ;   the caller's stack exactly as it arrived
    dw 0xffff, 0x0000                   ;   SEG14 record #82

end_of_code:
    times 123 - (end_of_code - water_hook) db 0xcc     ; int3 up to 0e0f, the first fixup kept
