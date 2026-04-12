-- Replace the placeholders before executing this script.
create tablespace YOUR_APP_TS
datafile 'D:\dmdata\YOUR_APP_TS.DBF'
size 512
autoextend on next 128
maxsize 8192;

create user YOUR_APP_USER
identified by "ChangeMe_123!"
default tablespace YOUR_APP_TS
default index tablespace YOUR_APP_TS;

grant PUBLIC, RESOURCE, SOI, SVI, VTI to YOUR_APP_USER;
