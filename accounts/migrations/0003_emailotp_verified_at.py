from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_emailotp")]

    operations = [
        migrations.AddField(
            model_name="emailotp",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]