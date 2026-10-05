// Exercise the same parser and state application used by the production binary.
#define main rave_engine_main
#include "../agents/Group026/RAVE_TS.cpp"
#undef main

void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

std::string empty_board() {
    std::string result;
    for (int row = 0; row < BOARD_SIZE; ++row) {
        if (row) result += ',';
        result += std::string(BOARD_SIZE, '0');
    }
    return result;
}

void reject(const std::string& input) {
    try { parse_request(input); }
    catch (const std::exception&) { return; }
    throw std::runtime_error("Invalid input was accepted.");
}

int main(int argc, char* argv[]) {
    try {
        if (argc == 3 && std::string(argv[1]) == "--trace") {
            Agent agent(std::string(argv[2]) == "R" ? RED : BLUE);
            std::string line;
            while (std::getline(std::cin, line)) {
                apply_request(agent, parse_request(line));
                std::cout << (agent.my_colour == RED ? 'R' : 'B') << '\n';
            }
            return 0;
        }
        const std::string board = empty_board();
        Agent recipient(RED), initiator(BLUE);
        apply_request(recipient, parse_request("V2;R;11;START;;" + board + ";1"));
        apply_request(initiator, parse_request("V2;B;11;CHANGE;5,5;" + board + ";2"));
        apply_request(recipient, parse_request("V2;B;11;SWAP;;" + board + ";3"));
        require(recipient.my_colour == BLUE, "Swap recipient retained its original colour.");
        apply_request(initiator, parse_request("V2;R;11;CHANGE;0,0;" + board + ";4"));
        require(initiator.my_colour == RED, "Swap initiator retained its original colour.");
        apply_request(recipient, parse_request("V2;B;11;CHANGE;0,1;" + board + ";5"));
        require(recipient.my_colour == BLUE, "Subsequent CHANGE lost the current role.");
        reject("V2;B;3;SWAP;;R00,000,000;3");
        reject("START;;" + board + ";1;");
        reject("V2;X;11;START;;" + board + ";1");
        reject("V2;R;11;CHANGE;11,0;" + board + ";2");
        reject("V2;R;11;START;;000;1");
        reject("V2;R;11;START;;" + board + ";0");
        std::cout << "Native role and input regression checks passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
