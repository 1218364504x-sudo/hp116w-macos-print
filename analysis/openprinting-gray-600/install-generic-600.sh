#!/bin/bash
# Minimal manual installer for the validated 600 dpi generic opt-in.
#
# This script owns exactly three production files.  It never invokes CUPS,
# submits a job, opens a device URI, or changes a queue/PPD/backend.
set -u
umask 077

SCRIPT_DIR="$(cd -- "$(/usr/bin/dirname -- "$0")" && pwd -P)"

SOURCE_ROUTER="$SCRIPT_DIR/../wps-docx-halftone-fix/hp116w-smart-router-dev/hp116w_smart_router"
SOURCE_CONFIG="$SCRIPT_DIR/../wps-docx-halftone-fix/hp116w-smart-router-dev/smart-router-config.json"
SOURCE_ADAPTER="$SCRIPT_DIR/../wps-docx-halftone-fix/hp116w-smart-router-dev/production-runtime/runtime/hp116w_generic_600.py"

TARGET_ROUTER='/usr/libexec/cups/filter/hp116w_smart_router'
TARGET_CONFIG='/usr/libexec/cups/filter/smart-router-config.json'
TARGET_ADAPTER='/Library/Application Support/HP116W/runtime/hp116w_generic_600.py'

PPD_600='/private/etc/cups/ppd/HP116W_600dpi.ppd'
PPD_1200='/private/etc/cups/ppd/HP116W_1200dpi.ppd'
RASTERTOQPDL='/usr/libexec/cups/filter/rastertoqpdl'
BASELINE_PPD='/Library/Application Support/HP116W/baseline/HP116W_High_Quality_NATIVE.ppd'
WRAPPER='/usr/libexec/cups/filter/hp116w_smart_cups_filter'
ROUTER_LOG_ANALYZER="$SCRIPT_DIR/../wps-docx-halftone-fix/print-quality-validation/analyze_spl3_capture.py"

EXPECTED_ROUTER_SHA='f91c01db85c9c15d2dc8d410cf36ae62382dbbc383f82d4d6036b31894baf37d'
EXPECTED_CONFIG_SHA='9a45f1da31f4e5fce63207997dc6ae37aa7b75535b8a920386cf249708131f05'
EXPECTED_ADAPTER_SHA='311dc1c403f1a0ebb223f5323729ff1b1cd2d532f2cbb8b76c71ebffc4245e29'
EXPECTED_PPD_600_SHA='995c0dd606f6f05f4328916cffd87c8d2ccf010fae5c6e463a5613b94a588495'
EXPECTED_PPD_1200_SHA='3b2234e66391f323e7420796d00239f4a5dfcf0a24606d48799a69818c95f1e9'
EXPECTED_RASTERTOQPDL_SHA='d2929bac0adee4fda83bd601fa84c219cff5891a7ffaff3414f22a99101dd4e5'

BACKUP_DIR="$SCRIPT_DIR/.install-generic-600-backup"
BACKUP_MANIFEST="$BACKUP_DIR/manifest.tsv"

BAD_PDF='/Volumes/项目用盘 4T/01个人/韩语/文档资料/背诵/韩语每日背诵_Day01_2026-08-16.pdf'
GOOD_PDF="$SCRIPT_DIR/../wps-docx-halftone-fix/hp116w-smart-router-dev/test-fixtures/WPS_DAY01_HIGH_CONFIDENCE.pdf"
NORMAL_PDF="$SCRIPT_DIR/../wps-docx-halftone-fix/hp116w-smart-router-dev/test-fixtures/NORMAL_PDF_NATIVE_BYPASS.pdf"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

sha256() {
  /usr/bin/shasum -a 256 -- "$1" | /usr/bin/awk '{print $1}'
}

hash_or_missing() {
  if [[ -f "$1" ]]; then
    sha256 "$1"
  else
    printf 'MISSING\n'
  fi
}

require_file() {
  [[ -f "$1" && ! -L "$1" ]] || die "regular file required: $1"
}

require_source_hashes() {
  require_file "$SOURCE_ROUTER"
  require_file "$SOURCE_CONFIG"
  require_file "$SOURCE_ADAPTER"
  [[ "$(sha256 "$SOURCE_ROUTER")" == "$EXPECTED_ROUTER_SHA" ]] || die 'source router hash mismatch'
  [[ "$(sha256 "$SOURCE_CONFIG")" == "$EXPECTED_CONFIG_SHA" ]] || die 'source config hash mismatch'
  [[ "$(sha256 "$SOURCE_ADAPTER")" == "$EXPECTED_ADAPTER_SHA" ]] || die 'source adapter hash mismatch'
}

protected_hashes() {
  require_file "$PPD_600"
  require_file "$PPD_1200"
  require_file "$RASTERTOQPDL"
  [[ "$(sha256 "$PPD_600")" == "$EXPECTED_PPD_600_SHA" ]] || die '600 dpi PPD hash mismatch'
  [[ "$(sha256 "$PPD_1200")" == "$EXPECTED_PPD_1200_SHA" ]] || die '1200 dpi PPD hash mismatch'
  [[ "$(sha256 "$RASTERTOQPDL")" == "$EXPECTED_RASTERTOQPDL_SHA" ]] || die 'rastertoqpdl hash mismatch'
}

show_file_pair() {
  local source="$1" target="$2"
  printf 'SOURCE  %s\n' "$source"
  printf '  SHA256 %s\n' "$(hash_or_missing "$source")"
  printf 'TARGET  %s\n' "$target"
  printf '  SHA256 %s\n' "$(hash_or_missing "$target")"
}

check() {
  require_source_hashes
  protected_hashes
  show_file_pair "$SOURCE_ROUTER" "$TARGET_ROUTER"
  show_file_pair "$SOURCE_CONFIG" "$TARGET_CONFIG"
  show_file_pair "$SOURCE_ADAPTER" "$TARGET_ADAPTER"
  printf 'PROTECTED_600_PPD       %s\n' "$(sha256 "$PPD_600")"
  printf 'PROTECTED_1200_PPD      %s\n' "$(sha256 "$PPD_1200")"
  printf 'PROTECTED_RASTERTOQPDL %s\n' "$(sha256 "$RASTERTOQPDL")"
  printf 'MODIFICATION_LIST      %s\n' "$TARGET_ROUTER | $TARGET_CONFIG | $TARGET_ADAPTER"
  printf 'PROTECTED_NOT_IN_LIST  PASS\n'
  printf 'CHECK                   PASS\n'
}

backup_one() {
  local key="$1" target="$2" backup="$3"
  local owner group mode
  if [[ -e "$target" ]]; then
    [[ -f "$target" && ! -L "$target" ]] || die "managed target is not a regular file: $target"
    owner=$(/usr/bin/stat -f '%Su' "$target")
    group=$(/usr/bin/stat -f '%Sg' "$target")
    mode=$(/usr/bin/stat -f '%Lp' "$target")
    /usr/bin/sudo /bin/cp -p "$target" "$backup" || die "cannot backup: $target"
    printf '%s\t%s\t%s\t%s\t%s\t%s\ttrue\n' "$key" "$target" "$backup" "$owner" "$group" "$mode" >> "$BACKUP_MANIFEST"
  else
    printf '%s\t%s\t%s\troot\twheel\t755\tfalse\n' "$key" "$target" "$backup" >> "$BACKUP_MANIFEST"
  fi
}

backup_targets() {
  [[ ! -e "$BACKUP_DIR" ]] || die "backup already exists; run rollback first: $BACKUP_DIR"
  /bin/mkdir "$BACKUP_DIR" || die "cannot create backup directory: $BACKUP_DIR"
  : > "$BACKUP_MANIFEST" || die "cannot create backup manifest"
  backup_one router "$TARGET_ROUTER" "$BACKUP_DIR/router"
  backup_one config "$TARGET_CONFIG" "$BACKUP_DIR/config"
  backup_one adapter "$TARGET_ADAPTER" "$BACKUP_DIR/adapter"
  /bin/chmod 600 "$BACKUP_MANIFEST"
}

install_one() {
  local source="$1" target="$2" default_mode="$3"
  local owner group mode temporary
  if [[ -f "$target" && ! -L "$target" ]]; then
    owner=$(/usr/bin/stat -f '%Su' "$target")
    group=$(/usr/bin/stat -f '%Sg' "$target")
    mode=$(/usr/bin/stat -f '%Lp' "$target")
  else
    owner=root
    group=wheel
    mode="$default_mode"
  fi
  temporary="${target}.generic-600-new.$$"
  if ! /usr/bin/sudo /usr/bin/install -o "$owner" -g "$group" -m "$mode" "$source" "$temporary"; then
    /usr/bin/sudo /bin/rm -f "$temporary" >/dev/null 2>&1 || true
    return 1
  fi
  if ! /usr/bin/sudo /bin/mv -f "$temporary" "$target"; then
    /usr/bin/sudo /bin/rm -f "$temporary" >/dev/null 2>&1 || true
    return 1
  fi
  return 0
}

restore_from_manifest() {
  local key target backup owner group mode existed temporary
  [[ -f "$BACKUP_MANIFEST" ]] || die "backup manifest missing: $BACKUP_MANIFEST"
  while IFS=$'\t' read -r key target backup owner group mode existed; do
    [[ -n "$key" ]] || continue
    if [[ "$existed" == true ]]; then
      temporary="${target}.generic-600-restore.$$"
      /usr/bin/sudo /usr/bin/install -o "$owner" -g "$group" -m "$mode" "$backup" "$temporary" || return 1
      /usr/bin/sudo /bin/mv -f "$temporary" "$target" || return 1
    else
      /usr/bin/sudo /bin/rm -f "$target" || return 1
    fi
  done < "$BACKUP_MANIFEST"
  return 0
}

rollback_internal() {
  if ! restore_from_manifest; then
    printf 'ERROR: automatic rollback failed; backup retained at %s\n' "$BACKUP_DIR" >&2
    return 1
  fi
  /bin/rm -rf "$BACKUP_DIR"
  printf 'ROLLBACK PASS\n'
  return 0
}

install_files() {
  require_source_hashes
  protected_hashes
  backup_targets
  if ! install_one "$SOURCE_ROUTER" "$TARGET_ROUTER" 755 || \
     ! install_one "$SOURCE_CONFIG" "$TARGET_CONFIG" 644 || \
     ! install_one "$SOURCE_ADAPTER" "$TARGET_ADAPTER" 755; then
    printf 'ERROR: install failed; restoring the three-file backup\n' >&2
    rollback_internal || exit 1
    exit 1
  fi
  if [[ "$(hash_or_missing "$TARGET_ROUTER")" != "$EXPECTED_ROUTER_SHA" || \
        "$(hash_or_missing "$TARGET_CONFIG")" != "$EXPECTED_CONFIG_SHA" || \
        "$(hash_or_missing "$TARGET_ADAPTER")" != "$EXPECTED_ADAPTER_SHA" || \
        "$(sha256 "$PPD_1200")" != "$EXPECTED_PPD_1200_SHA" || \
        "$(sha256 "$RASTERTOQPDL")" != "$EXPECTED_RASTERTOQPDL_SHA" ]]; then
    printf 'ERROR: post-install hash check failed; restoring the three-file backup\n' >&2
    rollback_internal || exit 1
    exit 1
  fi
  printf 'INSTALL PASS\n'
  printf 'BACKUP_DIR %s\n' "$BACKUP_DIR"
  printf 'Production queue/PPD/backend/network: untouched\n'
}

rollback() {
  [[ -d "$BACKUP_DIR" ]] || die "no backup found: $BACKUP_DIR"
  restore_from_manifest || die 'rollback failed; backup retained'
  /bin/rm -rf "$BACKUP_DIR"
  printf 'ROLLBACK PASS\n'
  printf 'Production queue/PPD/backend/network: untouched\n'
}

verify_target_hashes() {
  [[ "$(hash_or_missing "$TARGET_ROUTER")" == "$EXPECTED_ROUTER_SHA" ]] || die 'installed router hash mismatch'
  [[ "$(hash_or_missing "$TARGET_CONFIG")" == "$EXPECTED_CONFIG_SHA" ]] || die 'installed config hash mismatch'
  [[ "$(hash_or_missing "$TARGET_ADAPTER")" == "$EXPECTED_ADAPTER_SHA" ]] || die 'installed adapter hash mismatch'
  protected_hashes
}

verify_spl() {
  local spl="$1" json="$2"
  /usr/bin/python3 "$ROUTER_LOG_ANALYZER" "$spl" > "$json" || die "SPL analyzer failed: $spl"
  /usr/bin/jq -e '
    .valid == true and (.page_count >= 1) and
    (.pages | all(.copies == 1)) and
    (.pages | all(.resolution_dpi == [600,600])) and
    (.compression_codes == ["0x11"]) and
    (.checksum_failures == []) and
    (.framing.final_uel == true)
  ' "$json" >/dev/null || die "QPDL validation failed: $spl"
}

verify_case() {
  local label="$1" source="$2" expected_route="$3" work="$4"
  local job="verify-generic-600-$label"
  local options='ColorModel=Gray PageSize=A4 Quality=600dpi Resolution=600dpi Duplex=None sides=one-sided'
  local log_root="$work/$label"
  local router_log="$log_root/router"
  local wrapper_log="$log_root/wrapper"
  local dispatcher_log="$log_root/dispatcher"
  local spl="$log_root/output.spl"
  local json="$log_root/spl.json"
  local route pages spl_pages encoder_count
  /bin/mkdir -p "$router_log" "$wrapper_log" "$dispatcher_log"
  /usr/bin/env -i \
    PATH='/usr/bin:/bin:/usr/sbin:/usr/libexec/cups/filter' \
    HOME="$work/home" TMPDIR="$work/tmp" USER=_lp LOGNAME=_lp PYTHONNOUSERSITE=1 \
    PRINTER=HP116W_600dpi PPD="$PPD_600" \
    HP116W_SMART_CONFIG="$TARGET_CONFIG" \
    HP116W_SMART_LOG_DIR="$router_log" \
    HP116W_SMART_DISPATCHER_LOG_DIR="$dispatcher_log" \
    HP116W_SMART_WRAPPER_LOG_DIR="$wrapper_log" \
    "$WRAPPER" "$job" offline-user "$label.pdf" 1 "$options" "$source" \
    > "$spl" 2> "$log_root/stderr.log" || die "production wrapper failed: $label"
  verify_spl "$spl" "$json"
  route=$(/usr/bin/jq -r '.branch' "$router_log/job-$job.json")
  pages=$(/usr/bin/jq -r '.raster.page_count' "$router_log/job-$job.json")
  spl_pages=$(/usr/bin/jq -r '.page_count' "$json")
  encoder_count=$(/usr/bin/jq -r '.encoder_invocations' "$wrapper_log/job-$job.json")
  [[ "$route" == "$expected_route" ]] || die "$label route=$route expected=$expected_route"
  [[ "$pages" =~ ^[0-9]+$ && "$pages" -ge 1 ]] || die "$label page count invalid: $pages"
  [[ "$spl_pages" == "$pages" ]] || die "$label QPDL page count=$spl_pages raster page count=$pages"
  /usr/bin/jq -e '(.raster.pages | all(.width == 4750 and .height == 6808 and .bytes_per_line == 594))' \
    "$router_log/job-$job.json" >/dev/null || die "$label Raster geometry invalid"
  [[ "$encoder_count" == 1 ]] || die "$label rastertoqpdl invocation count=$encoder_count"
  printf '%s route=%s pages=%s copies=1 rastertoqpdl=PASS QPDL=PASS\n' "$label" "$route" "$pages"
}

verify() {
  verify_target_hashes
  [[ -f "$BAD_PDF" && -f "$GOOD_PDF" && -f "$NORMAL_PDF" ]] || die 'fixture missing'
  local work
  work=$(/usr/bin/mktemp -d /private/tmp/hp116w-generic-600-verify.XXXXXX) || die 'cannot create verify temp directory'
  /bin/mkdir -p "$work/home" "$work/tmp"
  VERIFY_WORK="$work"
  trap '/bin/rm -rf "$VERIFY_WORK"' EXIT
  verify_case BAD_SMask "$BAD_PDF" GENERIC_HIGHLIGHT_A "$work"
  verify_case GOOD_WPS "$GOOD_PDF" WPS_SELECTIVE "$work"
  verify_case NORMAL_IMAGE "$NORMAL_PDF" NATIVE_BYPASS "$work"

  local options1200='ColorModel=Gray PageSize=A4 Quality=High Resolution=1200dpi Duplex=None sides=one-sided'
  local log1200="$work/1200-router"
  local job1200='verify-generic-600-1200'
  /bin/mkdir -p "$log1200"
  /usr/bin/env -i \
    PATH='/usr/bin:/bin:/usr/sbin:/usr/libexec/cups/filter' \
    HOME="$work/home" TMPDIR="$work/tmp" USER=_lp LOGNAME=_lp PYTHONNOUSERSITE=1 \
    PRINTER=HP116W_1200dpi PPD="$PPD_1200" \
    HP116W_SMART_CONFIG="$TARGET_CONFIG" \
    HP116W_SMART_LOG_DIR="$log1200" \
    HP116W_SMART_DISPATCHER_LOG_DIR="$log1200" \
    "$TARGET_ROUTER" "$job1200" offline-user BAD.pdf 1 "$options1200" "$BAD_PDF" \
    > "$work/1200.raster" 2> "$work/1200.stderr" || die '1200 router verification failed'
  /usr/bin/jq -e '.status == "PASS" and .branch != "GENERIC_HIGHLIGHT_A" and (.generic_gate.eligible == false)' \
    "$log1200/job-$job1200.json" >/dev/null || die '1200 generic gate was not false'
  printf '1200 gate=false route=NATIVE_BYPASS generic=disabled\n'
  printf 'VERIFY PASS\n'
}

usage() {
  printf 'usage: %s {check|install|verify|rollback}\n' "$0" >&2
  exit 2
}

case "${1:-}" in
  check) check ;;
  install) install_files ;;
  verify) verify ;;
  rollback) rollback ;;
  *) usage ;;
esac
