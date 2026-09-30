from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0008_startup_plan_startup_plan_expires_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="fundingopportunity",
            name="source_posted_opportunity",
            field=models.ForeignKey(
                blank=True,
                help_text="Shared board opportunity this pipeline item was created from.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pipeline_opportunities",
                to="workspace.postedopportunity",
            ),
        ),
    ]
