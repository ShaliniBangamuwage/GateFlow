package apikey

import "testing"

func TestGeneratedKeyIsRandomAndVerifiable(t *testing.T) {
	first, prefix, hash, err := Generate()
	if err != nil {
		t.Fatal(err)
	}
	second, _, _, err := Generate()
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("generated keys must be unique")
	}
	if len(first) < 40 || len(prefix) == 0 {
		t.Fatal("generated key or prefix is unexpectedly short")
	}
	if !Verify(first, hash) {
		t.Fatal("generated key should verify")
	}
	if Verify(second, hash) {
		t.Fatal("different key should not verify")
	}
}
