from django import forms

from spoor.modules.cases.enums import CaseType


class CaseForm(forms.Form):
    name = forms.CharField(max_length=200)
    case_type = forms.ChoiceField(choices=CaseType.choices, label="Type")
    description = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Summary"
    )
