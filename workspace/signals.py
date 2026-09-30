from django.apps import apps
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .utils import ensure_default_document_categories


@receiver(post_migrate)
def seed_document_categories(sender, **kwargs):
    app_config = apps.get_app_config("workspace")
    if sender == app_config:
        ensure_default_document_categories()


@receiver(post_save, sender="workspace.PostedOpportunity")
def auto_match_on_new_opportunity(sender, instance, created, **kwargs):
    """When a new open opportunity is posted, run the matching agent for it."""
    if not created:
        return
    if instance.status != "open":
        return
    from .ai_pipeline import run_matching_agent
    run_matching_agent(trigger="signal", triggered_by=instance.posted_by, target_opportunity=instance)
