# Shared by tests/run_tests.sh and each firmware's tests/run.sh (sourced, from the top of the repository).
# base_test NAME CC ARGS...: compile to build/NAME and run it; its last line is its result, its whole output is shown
# when it fails
base_test() { t="$1"; shift; "$@" -o "build/$t"; "build/$t" > "build/$t.log" || { cat "build/$t.log"; exit 1; }; tail -1 "build/$t.log"; }
