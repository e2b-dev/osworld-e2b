"""Minimal VMManager adapter; the localhost relay owns E2B lifecycle.

Intentionally NOT subclassing the VMManager ABC: DesktopEnv only ever calls
`get_vm_path` on the manager, and the ABC declares several abstract methods
(check_and_clean, etc.) that are irrelevant when an external orchestrator owns
the sandbox lifecycle.
"""

import os

from .e2b_policy import require_immutable_template_ref


class E2BVMManager:
    def get_vm_path(self, os_type=None, region=None, screen_size=None, **kwargs):
        return require_immutable_template_ref(
            os.environ.get("GUEST_TEMPLATE"),
            "GUEST_TEMPLATE",
        )

    def check_and_clean(self, *args, **kwargs):
        pass

    def initialize_registry(self, **kwargs):
        pass

    def add_vm(self, *args, **kwargs):
        pass

    def delete_vm(self, *args, **kwargs):
        pass

    def occupy_vm(self, *args, **kwargs):
        pass

    def list_free_vms(self, **kwargs):
        return []
