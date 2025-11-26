CREATE USER cesfam_user WITH PASSWORD 'tu_contrasena_segura';
CREATE DATABASE cesfam_intranet_db OWNER cesfam_user;
\c cesfam_intranet_db
GRANT ALL ON SCHEMA public TO cesfam_user;
