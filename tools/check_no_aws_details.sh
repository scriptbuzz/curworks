#!/bin/bash
# CurWork Beta 0.015 - DRAFT - For Internal Use (FPT) - AWS details check - updated 2026-11-23 00:55 UTC - modified by: mbitar
# Blocks a commit or push if any file holds AWS account numbers, sign-in URLs, email addresses, access keys,
# private keys, or any value from your private curwork_test.env. Used by .githooks/pre-commit and pre-push,
# and by the automated tests. Usage:
#   check_no_aws_details.sh --staged          files about to be committed
#   check_no_aws_details.sh --commits A..B    files in the commits about to be pushed
#   check_no_aws_details.sh --worktree        every file Git would add (not ignored)
# Made-up example values used in samples and tests are allowed (see ALLOW below).
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "Not in a Git repository."; exit 2; }
cd "$ROOT" || exit 2
MODE="${1:---worktree}"; RANGE="${2:-}"
LIST="$(mktemp "${TMPDIR:-/tmp}/cw-files.XXXXXX")"; trap 'rm -f "$LIST" "$LIST".*' EXIT
case "$MODE" in
  --staged)   git diff --cached --name-only --diff-filter=ACMR -z > "$LIST" ;;
  --commits)  git diff --name-only --diff-filter=ACMR -z "$RANGE" > "$LIST" ;;
  --worktree) { git ls-files -z; git ls-files -o --exclude-standard -z; } > "$LIST" ;;
  *) echo "Unknown option $MODE"; exit 2 ;;
esac
# Values from your private settings file are always blocked.
PRIVATE=""
if [ -f curwork_test.env ]; then
  PRIVATE="$(grep -E '^(CURWORK_ACCOUNT|CURWORK_ADMIN_PROFILE|CURWORK_SSO_START_URL|CURWORK_IC_PROFILE)=' curwork_test.env \
             | cut -d= -f2- | sed 's/[[:space:]]*$//' | grep -v -E '^$' | tr '\n' '\t')"
fi
export PRIVATE MODE RANGE
perl -0 -e '
  my @allow = qw(123456789012 000000000000 000011112222 004455667788 012345678901 000099998888 007766554433 111111111111);
  my %allow = map { $_ => 1 } @allow;
  my @private = grep { length } split /\t/, ($ENV{PRIVATE} // "");
  my $bad = 0;
  local $/ = "\0"; my @files = <STDIN>; chomp @files;
  for my $f (@files) {
    next if $f eq "curwork_test.env" || $f =~ m{(^|/)curwork_test\.env\.example$} || $f =~ m{(^|/)tools/check_no_aws_details\.sh$};
    my $text;
    if ($ENV{MODE} eq "--commits") { my ($to) = $ENV{RANGE} =~ /\.\.(.+)$/; $to ||= "HEAD"; $text = `git show "$to:$f" 2>/dev/null`; }
    elsif ($ENV{MODE} eq "--staged") { $text = `git show ":$f" 2>/dev/null`; }
    else { next unless -f $f; open(my $h, "<", $f) or next; local $/; $text = <$h>; close $h; }
    next unless defined $text;
    my $meta = ($text =~ /caBX|c2pa|jumbf/i);                                    # embedded content-credential metadata
    next if $f =~ /\.(png|ico|icns|xlsx|zip)$/i && !$meta;                       # binary: only the metadata check
    my @hits;
    for my $v (@private) { push @hits, "a value from curwork_test.env" if index($text, $v) >= 0; }
    while ($text =~ /(?<![0-9A-Za-z])(\d{12})(?![0-9A-Za-z])/g) { push @hits, "AWS account number $1" unless $allow{$1}; }
    while ($text =~ /\b([a-z0-9-]+)\.awsapps\.com/g) { push @hits, "sign-in URL $1.awsapps.com" unless $1 =~ /^(example|x|your-org)$/; }
    while ($text =~ /\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b/g) { my $e=$1; push @hits, "email address $e" unless $e =~ /\@(example\.com|x\.com|x)$/i; }
    push @hits, "AWS access key"  if $text =~ /\b(AKIA|ASIA)[0-9A-Z]{16}\b/;
    push @hits, "Identity Center instance id" if $text =~ /\bssoins-[0-9a-f]{16}\b/;
    push @hits, "private key"     if $text =~ /-----BEGIN [A-Z ]*PRIVATE KEY-----/;
    push @hits, "secret key value" if $text =~ /aws_secret_access_key\s*=\s*[A-Za-z0-9\/+]{30,}/;
    push @hits, "embedded content-credential metadata (strip it)" if $meta && $f =~ /\.(png|ico|icns|xlsx|zip)$/i;
    if (@hits) { my %s; @hits = grep { !$s{$_}++ } @hits; print "  BLOCKED  $f: ", join("; ", @hits), "\n"; $bad = 1; }
  }
  exit $bad;
' < "$LIST"
RC=$?
if [ $RC -ne 0 ]; then
  echo "Remove these details (move them to curwork_test.env, which Git ignores), then try again."
else
  echo "  PASS  no AWS account numbers, sign-in URLs, emails, keys or private values in the files checked"
fi
exit $RC
