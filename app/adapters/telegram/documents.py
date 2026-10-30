"""Telegram document compatibility methods; business operations live in the core."""
from app.services.documents import DuplicateCheckResult, DocumentValidationError
from app.schemas.document import DocumentSchema
from app.schemas.project import Project
from app.services.documents import DocumentService as Core
from app.adapters.telegram.companies import CompanyService, actor


class DocumentService(Core):
    @property
    def company_service(self):
        # Legacy Telegram entry points resolve identities at their boundary.
        from app.adapters.telegram.companies import CompanyService
        return CompanyService()

    async def save_document(
        self,
        telegram_user,
        project: Project,
        normalized_text: str,
        document: DocumentSchema,
        duplicate_check: DuplicateCheckResult | None = None,
        source_type: str = "photo",
        upload_id: str | None = None,
    ) -> int:
        actor = await self.company_service._workspace_actor(telegram_user.id)
        return await self.save_for_user(actor, project.id, normalized_text, document,
                                        source_type=source_type, upload_id=upload_id)

    async def find_company_duplicate_document(
        self,
        telegram_user,
        project: Project,
        document: DocumentSchema,
        normalized_text: str | None = None,
    ) -> DuplicateCheckResult:
        actor = await self.company_service._workspace_actor(telegram_user.id)
        return await self.find_duplicate_for_user(actor, project.id, document, normalized_text)

    async def get_duplicate_document_info(self, external_id, *args, **kwargs):
        return await super().get_duplicate_document_info(await actor(external_id), *args, **kwargs)

    async def resolve_duplicate_keep_separate(self, external_id, *args, **kwargs):
        return await super().resolve_duplicate_keep_separate(await actor(external_id), *args, **kwargs)

    async def delete_source_duplicate_document(self, external_id, *args, **kwargs):
        return await super().delete_source_duplicate_document(await actor(external_id), *args, **kwargs)

    async def delete_duplicate_document(self, external_id, *args, **kwargs):
        return await super().delete_duplicate_document(await actor(external_id), *args, **kwargs)

    async def cleanup_broken_duplicate_links(self, external_id, *args, **kwargs):
        return await super().cleanup_broken_duplicate_links(await actor(external_id), *args, **kwargs)
