# Run as the database file owner in the private Linux benchmark container.
# Evict only relation files belonging to the new benchmark database, then
# measure residency for the supplied search corpus filenodes without faulting pages in.
use strict;
use warnings;
use Fcntl qw(O_RDONLY);
use POSIX qw(sysconf _SC_PAGESIZE);
use JSON::PP;
require 'syscall.ph';

my $mode = shift;
die "invalid mode" unless $mode eq "inspect" || $mode eq "evict";
my ($oid, @corpus) = @ARGV;
die "invalid database or filenode" if !@corpus || grep { !/^\d+$/ } @ARGV;
my %tracked = map { $_ => 1 } @corpus;
my $dir = "$ENV{PGDATA}/base/$oid";
die "unexpected data directory" unless $ENV{PGDATA} eq '/tmp/search-gate-pgdata';
opendir(my $dh, $dir) or die "$dir: $!";
my @files = grep { /^\d+(?:_(?:fsm|vm|init))?(?:\.\d+)?$/ } readdir($dh);
closedir($dh);
my $pagesize = sysconf(_SC_PAGESIZE);
my ($pages, $resident, $files) = (0, 0, 0);
for my $name (@files) {
    last if $mode eq "inspect";
    sysopen(my $fd, "$dir/$name", O_RDONLY) or die "$name: $!";
    # POSIX_FADV_DONTNEED on the calling process's own database files.
    syscall(&SYS_fadvise64, fileno($fd), 0, 0, 4) == 0 or die "fadvise $name: $!";
}
for my $name (@files) {
    my ($base) = $name =~ /^(\d+)/;
    next unless $tracked{$base};
    sysopen(my $fd, "$dir/$name", O_RDONLY) or die "$name: $!";
    my $size = -s $fd;
    next unless $size;
    my $n = int(($size + $pagesize - 1) / $pagesize);
    my $bits = "\0" x $n;
    # PROT_NONE, MAP_SHARED: mincore inspects the mapping without touching its data.
    my $addr = syscall(&SYS_mmap, 0, $size, 0, 1, fileno($fd), 0);
    die "mmap $name: $!" if $addr == -1;
    syscall(&SYS_mincore, $addr, $size, $bits) == 0 or die "mincore $name: $!";
    syscall(&SYS_munmap, $addr, $size) == 0 or die "munmap $name: $!";
    $resident += unpack('%32b*', $bits & ("\1" x $n));
    $pages += $n;
    $files++;
}
die "empty corpus" unless $pages && $files;
print encode_json({files => $files, pages => $pages, resident => $resident, page_size => $pagesize});
