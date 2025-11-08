#!/bin/bash

targDir=/home/kanashi/Bilder/wallpaper

cd /mnt/anime/torrents/completed/anime

find . -type d | 
 while IFS="" read -r dir ; do
   if [[ -f "${dir}"/fanart.jpg ]] ; then
     cp -i "${dir}/fanart.jpg" "${targDir}/${dir:2}.jpg"
   fi
done
