#!/bin/bash

mkdir -p twitter_in
mkdir -p twitter_out

eval() {
    # is=$(echo "scale=1; $@" | bc)
    # # >&2 echo "eval '$1' is '$is'"
    # echo $is
    echo "scale=10; $@" | bc
}

roundeval() {
    # evald=$(eval "$@")
    # is=$(printf %.0f $evald)
    # # >&2 echo "round '$evald' is '$is'"
    # echo $is
    printf %.0f $(eval "$@")
}

scale_to_ratio() {
    file=$1
    aspectw=$2
    aspecth=$3
    aspects="($aspectw/$aspecth)"
    aspectf=$(eval "$aspectw/$aspecth")

    IFS=, read width height <<< $(identify -format "%w,%h" "${file}")

    # echo "$aspects Pre ${width} x ${height} ($(eval "$width/$height") vs $aspectf) $aspects"

    # echo "$height * $aspects"
    perfectw=$(roundeval "$height * $aspects")
    if ((width < perfectw)); then
        # echo "$width < ($height * $aspects = $perfectw)"
        h=$height
        w=$(roundeval "$height * ($aspectw/$aspecth)")
        # echo "new w = $height * ($aspectw/$aspecth)"
    else
        # echo "$width >= ($height * $aspects = $perfectw)"
        w=$width
        h=$(roundeval "$width * ($aspecth/$aspectw)")
        # echo "new h = $width * ($aspecth/$aspectw)"
    fi

    # echo "$aspects Post ${w} x ${h} ($(eval "$w/$h") vs $aspectf)"
    filen=$(basename "$file")
    extension="${filen##*.}"
    filename="${filen%.*}"       

    if test -z "$4"
    then
        echo Blur 
        convert -verbose "${file}" \
            \( -clone 0 -blur 0x8 -resize ${w}x${h}^! \) \
            \( -clone 0 -resize ${w}x${h} \) \
            -delete 0 -gravity center -compose over -composite \
            "twitter_out/${filename}.${aspectw}x${aspecth}.${extension}"
    else
        echo Background "$4"
        convert -verbose \( -size ${w}x${h}^! canvas:$4 \) \
            "${file}" -gravity center -compose over -composite \
            "twitter_out/${filename}.${aspectw}x${aspecth}.${extension}"
    fi

    
}

for file in twitter_in/*.*
do 
    echo ${file}
    if [ -z "$2" ]
    then
        scale_to_ratio "${file}" 2 1
        scale_to_ratio "${file}" 7 8
        scale_to_ratio "${file}" 7 4
        scale_to_ratio "${file}" 16 9
        scale_to_ratio "${file}" 2 1 
        scale_to_ratio "${file}" 7 8 y
        scale_to_ratio "${file}" 7 4 y
        scale_to_ratio "${file}" 16 9 y
    else
        scale_to_ratio "${file}" $1 $2
    fi
    # parallel --jobs 3 -m scale_to_ratio "${f}" ::: 2 1 7 8 4 7
    
    filen=$(basename "$file")
    extension="${filen##*.}"
    filename="${filen%.*}"     
    mv -v "${file}" "twitter_out/${filename}.bak.${extension}"
done
