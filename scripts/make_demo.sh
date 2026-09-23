#!/usr/bin/env bash
set -euo pipefail

input="${1:?Usage: scripts/make_demo.sh /path/to/1.mp4 [output.mp4]}"
output="${2:-docs/demo.mp4}"
expected_hash='d6db08940fee77dc4a9a91e16b65d211056da87210cd2694f6e6195080922c13'
actual_hash="$(shasum -a 256 "$input" | cut -d ' ' -f 1)"
if [[ "$actual_hash" != "$expected_hash" ]]; then
  echo 'This demo uses the saved review for the original 1.mp4 only.' >&2
  exit 1
fi
font='/System/Library/Fonts/Supplemental/Arial.ttf'
bold='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
mkdir -p "$(dirname "$output")"

# The displayed figures are from the saved DUPRVision review of the sample 1.mp4.
ffmpeg -hide_banner -loglevel error -y -i "$input" -an -filter_complex "
 [0:v]fps=30,scale=360:640:flags=lanczos,setsar=1,
 pad=1280:720:70:40:color=0x0f1d1a,
 drawbox=x=478:y=40:w=732:h=640:color=0x182b26:t=fill,
 drawbox=x=506:y=139:w=66:h=4:color=0xd8ee63:t=fill,
 drawtext=fontfile='$bold':text='DUPRVision':fontcolor=white:fontsize=42:x=506:y=68,
 drawtext=fontfile='$font':text='GAMEPLAY REVIEW':fontcolor=0xb8c9c3:fontsize=20:x=506:y=160,
 drawtext=fontfile='$font':text='27-second gameplay clip':fontcolor=white:fontsize=25:x=506:y=207,
 drawtext=fontfile='$font':text='Upload  /  Select player  /  Review':fontcolor=0xb8c9c3:fontsize=19:x=506:y=249,
 drawtext=fontfile='$font':text='VISION SCORE':fontcolor=0xb8c9c3:fontsize=20:x=506:y=318:enable='gte(t,6)',
 drawtext=fontfile='$bold':text='97 / 100':fontcolor=0xd8ee63:fontsize=64:x=504:y=347:enable='gte(t,6)',
 drawtext=fontfile='$font':text='9 assessed shots  /  1 rally':fontcolor=white:fontsize=25:x=506:y=443:enable='gte(t,10)',
 drawtext=fontfile='$font':text='5 dinks  /  3 volleys  /  1 drive':fontcolor=0xb8c9c3:fontsize=21:x=506:y=482:enable='gte(t,10)',
 drawtext=fontfile='$font':text='NEXT PRACTICE':fontcolor=0xb8c9c3:fontsize=19:x=506:y=548:enable='gte(t,15)',
 drawtext=fontfile='$bold':text='Stay balanced in fast net exchanges':fontcolor=white:fontsize=21:x=506:y=580:enable='gte(t,15)',
 drawtext=fontfile='$font':text='AI observations can be wrong. Not an official DUPR rating.':fontcolor=0x9eafa9:fontsize=15:x=506:y=648
 [v]" -map '[v]' -c:v libx264 -preset medium -crf 24 -pix_fmt yuv420p -movflags +faststart "$output"
