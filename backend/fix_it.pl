#!/usr/bin/perl
use strict;
use warnings;

my $file = 'main.py';
open(my $fh, '<', $file) or die "Cannot open: $!";
my @lines = <$fh>;
close($fh);

# Insert workspace_path before line 282 (index 281)
my $ws_line = ' workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")\n';
splice(@lines, 281, 0, $ws_line);

# db = SessionLocal() is now at index 324 (originally 323, shifted by 1)
# Insert 3 lines before it
splice(@lines, 324, 0, " phase_passed = bool(runner_res->{passed}) if ref(runner_res) eq 'HASH' else 0\n");
splice(@lines, 325, 0, " phase_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n");
splice(@lines, 326, 0, " exec_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n");

open($fh, '>', $file) or die "Cannot write: $!";
print $fh @lines;
close($fh);

print "Done!\n";

# Verify
open($fh, '<', $file) or die;
@lines = <$fh>;
close($fh);
for my $i (280..290) { printf "%3d: %s", $i+1, $lines[$i]; }
print "---\n";
for my $i (323..337) { printf "%3d: %s", $i+1, $lines[$i]; }
