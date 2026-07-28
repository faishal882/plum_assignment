from fastapi import UploadFile


class FastAPIUploadSource:
    def __init__(self, upload: UploadFile) -> None:
        self._upload = upload
        self.filename = upload.filename
        self.content_type = upload.content_type

    async def read(self, size: int) -> bytes:
        return await self._upload.read(size)
