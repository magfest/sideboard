from sideboard.internal.imports import _yield_module_names_and_filenames_from_callstack

def c_func():

    module_names = list(m_name for m_name, file_name in _yield_module_names_and_filenames_from_callstack())
    # TODO: this is better done as an assertion about subsequences
    assert module_names[3] == 'tests.imports.overridden_import_modules_for_asserts.c', module_names
    assert module_names[4] == 'tests.imports.overridden_import_modules_for_asserts.b', module_names
    assert module_names[5] == 'tests.imports.overridden_import_modules_for_asserts.a'