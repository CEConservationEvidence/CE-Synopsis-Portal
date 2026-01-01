from django.db import migrations, models
import django.utils.timezone
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0044_reference_summary_synopsis_draft"),
    ]

    operations = [
        migrations.AddField(
            model_name="reference",
            name="reference_document",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="reference_documents/%Y/%m/%d",
                validators=[django.core.validators.FileExtensionValidator(["pdf"])],
                help_text="Optional uploaded PDF of the reference.",
            ),
        ),
        migrations.AddField(
            model_name="reference",
            name="reference_document_uploaded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
