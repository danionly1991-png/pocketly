-- Spec 03: public bucket for category icons + per-user-folder write policies.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('category-icons', 'category-icons', true, 524288, array['image/webp'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- Public URLs are served without RLS (public bucket). This SELECT policy is still
-- needed because Storage only deletes objects the caller can see (deviation D5).
create policy category_icons_select_own on storage.objects
  for select to authenticated
  using (bucket_id = 'category-icons'
         and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy category_icons_insert_own on storage.objects
  for insert to authenticated
  with check (bucket_id = 'category-icons'
              and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy category_icons_update_own on storage.objects
  for update to authenticated
  using (bucket_id = 'category-icons'
         and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'category-icons'
              and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy category_icons_delete_own on storage.objects
  for delete to authenticated
  using (bucket_id = 'category-icons'
         and (storage.foldername(name))[1] = (select auth.uid())::text);
