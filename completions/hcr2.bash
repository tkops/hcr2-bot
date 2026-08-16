# Bash completion for hcr2.
#
# Usage for the current shell:
#   source completions/hcr2.bash
#
# Persistent user install:
#   mkdir -p ~/.local/share/bash-completion/completions
#   cp completions/hcr2.bash ~/.local/share/bash-completion/completions/hcr2

_hcr2_comp_words()
{
    local words="$1"
    local cur="$2"
    COMPREPLY=( $(compgen -W "$words" -- "$cur") )
}

_hcr2_comp_files()
{
    local cur="$1"
    COMPREPLY=( $(compgen -f -- "$cur") )
}

_hcr2_entity_commands()
{
    case "$1" in
        vehicle) echo "list add edit delete import export drop" ;;
        player) echo "list list-active list-leader list-absent bday add edit activate deactivate delete show grep away back" ;;
        teamevent) echo "add list show edit delete" ;;
        season) echo "list add delete" ;;
        match) echo "add edit show list delete" ;;
        matchscore) echo "add list list-short delete edit" ;;
        stats) echo "perf avg alias rank te te-user scatter bdayplot battle absent player score points" ;;
        sheet) echo "create import player donations" ;;
        video) echo "list pull frames roster apply player chest" ;;
        distance) echo "list show weeks add delete" ;;
        donations) echo "add delete edit show stats under list" ;;
    esac
}

_hcr2_flags()
{
    local entity="$1"
    local command="$2"

    case "$entity:$command" in
        vehicle:add) echo "--name --short" ;;
        vehicle:edit) echo "--id --name --short" ;;
        vehicle:delete) echo "--id" ;;

        player:list|player:list-active) echo "--sort --team" ;;
        player:bday) echo "--active --num" ;;
        player:add) echo "--team --name --alias --gp --active --birthday --discord" ;;
        player:edit) echo "--id --name --alias --gp --active --birthday --team --discord --leader --about --vehicles --playstyle --language --emoji" ;;
        player:activate|player:deactivate|player:delete) echo "--id" ;;
        player:show|player:away|player:back) echo "--id --name --discord --dur" ;;

        teamevent:add) echo "--name --week --vehicles --tracks --score" ;;
        teamevent:list|teamevent:show) echo "--all --id" ;;
        teamevent:edit) echo "--id --name --tracks --vehicles --score" ;;
        teamevent:delete) echo "--id" ;;

        season:list) echo "--all --number --division" ;;
        season:add) echo "--number --division" ;;
        season:delete) echo "--number" ;;

        match:add) echo "--opponent --teamevent --season --start --score --scoreopp" ;;
        match:edit) echo "--id --teamevent --season --start --opponent --score --scoreopp" ;;
        match:show|match:delete) echo "--id" ;;
        match:list) echo "--season --all" ;;

        matchscore:add) echo "--match --player --score --points --absent --checkin" ;;
        matchscore:list|matchscore:list-short) echo "--all --match --season" ;;
        matchscore:delete) echo "--id" ;;
        matchscore:edit) echo "--id --score --points --pid --absent --checkin" ;;

        stats:perf) echo "--active" ;;
        stats:score|stats:points) echo "--skip --no-skip" ;;

        video:list|video:roster) echo "--match" ;;
        video:pull) echo "--match --file" ;;
        video:frames) echo "--match --file --fps --width --crop --start --duration" ;;
        video:apply) echo "--match --file --dry-run --force" ;;
        video:player) echo "--file --fps --width --crop --start --duration --dry-run --force" ;;
        video:chest) echo "--year --week --file --fps --width --crop --start --duration" ;;

        distance:list) echo "--year --week" ;;
        distance:show) echo "--player --num" ;;
        distance:weeks) echo "--num" ;;
        distance:add) echo "--player --km --year --week" ;;
        distance:delete) echo "--id" ;;

        donations:add) echo "--player --date --total" ;;
        donations:delete) echo "--id" ;;
        donations:edit) echo "--id" ;;
        donations:show) echo "--player" ;;
        donations:list) echo "--date" ;;
    esac
}

_hcr2_flag_values()
{
    local flag="$1"
    local cur="$2"

    case "$flag" in
        --active|--leader) _hcr2_comp_words "true false" "$cur" ;;
        --absent|--checkin) _hcr2_comp_words "true false 1 0 toggle" "$cur" ;;
        --sort) _hcr2_comp_words "gp name" "$cur" ;;
        --dur) _hcr2_comp_words "1w 2w 3w 4w" "$cur" ;;
        --division) _hcr2_comp_words "CC4 CC3 CC2 CC1 DC4 DC3 DC2 DC1" "$cur" ;;
        --all|--skip|--no-skip) COMPREPLY=() ;;
        *) COMPREPLY=() ;;
    esac
}

_hcr2()
{
    local cur prev entity command commands flags
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    if [[ "$prev" == --* ]]; then
        _hcr2_flag_values "$prev" "$cur"
        return
    fi

    if (( COMP_CWORD == 1 )); then
        _hcr2_comp_words "vehicle player teamevent season match matchscore stats sheet video distance donations version help -h --help" "$cur"
        return
    fi

    entity="${COMP_WORDS[1]}"
    if [[ "$entity" == "help" ]]; then
        _hcr2_comp_words "vehicle player teamevent season match matchscore stats sheet video distance donations version -h --help" "$cur"
        return
    fi

    if [[ "$entity" == "version" ]]; then
        COMPREPLY=()
        return
    fi

    if (( COMP_CWORD == 2 )); then
        commands="$(_hcr2_entity_commands "$entity")"
        _hcr2_comp_words "$commands help -h --help" "$cur"
        return
    fi

    command="${COMP_WORDS[2]}"

    if [[ "$entity" == "sheet" && ( "$command" == "player" || "$command" == "donations" ) && COMP_CWORD -eq 3 ]]; then
        _hcr2_comp_words "export import" "$cur"
        return
    fi

    if [[ "$entity" == "video" && "$command" == "player" && COMP_CWORD -eq 3 ]]; then
        _hcr2_comp_words "frames apply" "$cur"
        return
    fi

    if [[ "$entity" == "video" && "$command" == "chest" && COMP_CWORD -eq 3 ]]; then
        _hcr2_comp_words "frames" "$cur"
        return
    fi

    if [[ "$entity" == "player" && "$command" == "bday" && COMP_CWORD -eq 3 && "$cur" != --* ]]; then
        _hcr2_comp_words "today list" "$cur"
        return
    fi

    if [[ "$entity" == "vehicle" && "$command" == "import" ]]; then
        _hcr2_comp_files "$cur"
        return
    fi

    if [[ "$cur" == -* ]]; then
        flags="$(_hcr2_flags "$entity" "$command")"
        _hcr2_comp_words "$flags -h --help" "$cur"
        return
    fi

    COMPREPLY=()
}

complete -F _hcr2 hcr2 hcr2.py ./hcr2.py
