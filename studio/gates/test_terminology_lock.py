from terminology_lock import check_terminology, passes


def run_tests():
    source = "The contract is void."

    violations = check_terminology(source, "The contract is voidable.")
    assert len(violations) == 1
    assert violations[0].protected_term == "void"
    assert violations[0].found_synonym == "voidable"
    assert not passes(source, "The contract is voidable.")

    assert check_terminology(source, "The contract is void.") == []
    assert passes(source, "The contract is void.")

    assert check_terminology(source, "The contract is void, though another clause is voidable.") == []
    assert passes(source, "The contract is void, though another clause is voidable.")

    assert check_terminology("", "") == []
    assert passes("", "")

    print("OK")


if __name__ == "__main__":
    run_tests()
