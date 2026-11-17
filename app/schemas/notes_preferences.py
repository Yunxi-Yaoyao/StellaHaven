from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class NotesPreferencesRead(BaseModel):
    revision: int
    delete_action: Literal['trash', 'permanent']
    ask_before_delete: bool
    font_size: int = 16
    line_height: float = 1.8
    read_width: int = 800
    code_line_numbers: bool = False
    code_wrap: bool = True
    directory_sort: Literal['updated', 'title', 'created'] = 'updated'
    hidden_folders: list[str] = Field(default_factory=list)


class NotesPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0, strict=True)
    delete_action: Literal['trash', 'permanent'] | None = None
    ask_before_delete: StrictBool | None = None
    font_size: int | None = Field(default=None, ge=12, le=28, strict=True)
    line_height: float | None = Field(default=None, ge=1.2, le=2.5)
    read_width: int | None = Field(default=None, ge=480, le=1400, strict=True)
    code_line_numbers: StrictBool | None = None
    code_wrap: StrictBool | None = None
    directory_sort: Literal['updated', 'title', 'created'] | None = None
    hidden_folders: list[str] | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def no_explicit_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError('Preference fields cannot be null')
        if self.hidden_folders is not None:
            import re
            if any(not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value) for value in self.hidden_folders):
                raise ValueError('Folder IDs must be UUIDs')
            self.hidden_folders = list(dict.fromkeys(self.hidden_folders))
        return self
