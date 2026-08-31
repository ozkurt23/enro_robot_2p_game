from mecanum_kinematics.command_parser import ParsedCommand, parse_command


def test_user_blue_object_sentence_maps_to_main_table():
    assert parse_command("mavi cismi ana masaya götür") == ParsedCommand(
        "transfer", ("blue", "stack")
    )


def test_existing_readme_transfer_form_is_preserved():
    assert parse_command("yeşilden maviye taşı") == ParsedCommand(
        "transfer", ("green", "blue")
    )


def test_go_to_colored_table():
    assert parse_command("kırmızı masaya git") == ParsedCommand("go", ("red",))


def test_stack_all_cubes():
    assert parse_command("Tüm küpleri sırayla diz") == ParsedCommand("stack_all")


def test_same_source_and_target_is_rejected_before_motion():
    assert parse_command("maviden maviye taşı") == ParsedCommand(
        "reject_same_location", ("blue",)
    )


def test_unknown_text_does_not_guess_a_motor_action():
    assert parse_command("bugün hava nasıl") is None
